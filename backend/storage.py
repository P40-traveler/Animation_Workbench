import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException
from .models import uid, State


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'workspace.sqlite'
        self.lock = threading.RLock()
        with self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS objects(id TEXT PRIMARY KEY,kind TEXT,parent TEXT,name TEXT);
            CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY,action_id TEXT,name TEXT,revision INTEGER,state TEXT,undo TEXT,redo TEXT);
            CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,project_id TEXT,doc TEXT);
            CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,doc TEXT);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,doc TEXT);
            CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY AUTOINCREMENT,version_id TEXT,actor TEXT,operation TEXT,revision INTEGER,at TEXT);
            ''')
            for row in c.execute('SELECT id,doc FROM jobs').fetchall():
                job = json.loads(row['doc'])
                if job['status'] in ('queued', 'running'):
                    job.update(status='interrupted', error='服务重启，任务中断；可重新提交')
                    c.execute('UPDATE jobs SET doc=? WHERE id=?', (json.dumps(job), row['id']))

    @contextmanager
    def connect(self):
        with self.lock:
            c = sqlite3.connect(self.db, timeout=30)
            c.row_factory = sqlite3.Row
            try:
                yield c
                c.commit()
            except Exception:
                c.rollback()
                raise
            finally:
                c.close()

    def object(self, oid, kind=None):
        with self.connect() as c:
            row = c.execute('SELECT * FROM objects WHERE id=?', (oid,)).fetchone()
            if not row or (kind and row['kind'] != kind):
                raise HTTPException(404, '项目对象不存在')
            return dict(row)

    def create(self, kind, parent, name):
        if parent:
            self.object(parent, {'character': 'project', 'action': 'character'}[kind])
        obj = dict(id=uid(), kind=kind, parent=parent, name=name.strip() or '未命名')
        with self.connect() as c:
            c.execute('INSERT INTO objects VALUES(:id,:kind,:parent,:name)', obj)
        return obj

    def project_for(self, action_id):
        action = self.object(action_id, 'action')
        return self.object(action['parent'], 'character')['parent']

    def get_version(self, vid):
        with self.connect() as c:
            row = c.execute('SELECT * FROM versions WHERE id=?', (vid,)).fetchone()
            if not row:
                raise HTTPException(404, '版本不存在')
            v = dict(row)
            v['state'] = json.loads(v['state'])
            v['can_undo'] = bool(json.loads(v.pop('undo')))
            v['can_redo'] = bool(json.loads(v.pop('redo')))
            v['project_id'] = self.project_for(v['action_id'])
            return v

    def validate_refs(self, state, project_id):
        ids = set(state['prompt']['reference_ids'])
        ids.update(e['asset_id'] for t in state['tracks'] for e in t['exposures'])
        for aid in ids:
            if self.asset(aid)['project_id'] != project_id:
                raise HTTPException(422, '素材必须属于当前项目')

    def new_version(self, action_id, name, state=None):
        state = State.model_validate(state or {}).model_dump()
        self.validate_refs(state, self.project_for(action_id))
        vid = uid()
        with self.connect() as c:
            c.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?)', (vid, action_id, name, 1, json.dumps(state), '[]', '[]'))
        return self.get_version(vid)

    def save(self, vid, expected, state, actor='user', operation='save', name=None):
        state = State.model_validate(state).model_dump()
        with self.connect() as c:
            row = c.execute('SELECT * FROM versions WHERE id=?', (vid,)).fetchone()
            if not row:
                raise HTTPException(404, '版本不存在')
            if row['revision'] != expected:
                raise HTTPException(409, '版本已被另一端修改，请刷新或另存版本；本地修改仍保留')
            self.validate_refs(state, self.project_for(row['action_id']))
            history = json.loads(row['undo'])
            history.append(dict(state=json.loads(row['state']), name=row['name']))
            c.execute('UPDATE versions SET name=?,state=?,revision=?,undo=?,redo=? WHERE id=?',
                      (name or row['name'], json.dumps(state), expected+1, json.dumps(history[-80:]), '[]', vid))
            c.execute('INSERT INTO history(version_id,actor,operation,revision,at) VALUES(?,?,?,?,?)', (vid, actor, operation, expected+1, now()))
        return self.get_version(vid)

    def travel(self, vid, expected, direction, actor):
        with self.connect() as c:
            row = c.execute('SELECT * FROM versions WHERE id=?', (vid,)).fetchone()
            if not row:
                raise HTTPException(404, '版本不存在')
            if row['revision'] != expected:
                raise HTTPException(409, '撤销目标已变化，请刷新')
            undo, redo = json.loads(row['undo']), json.loads(row['redo'])
            source, target = (undo, redo) if direction == 'undo' else (redo, undo)
            if not source:
                raise HTTPException(422, '没有可撤销/重做的操作')
            snapshot = source.pop()
            target.append(dict(state=json.loads(row['state']), name=row['name']))
            c.execute('UPDATE versions SET state=?,name=?,revision=?,undo=?,redo=? WHERE id=?',
                      (json.dumps(snapshot['state']), snapshot['name'], expected+1, json.dumps(undo), json.dumps(redo), vid))
            c.execute('INSERT INTO history(version_id,actor,operation,revision,at) VALUES(?,?,?,?,?)', (vid, actor, direction, expected+1, now()))
        return self.get_version(vid)

    def asset(self, aid):
        return self.doc('assets', aid)

    def doc(self, table, oid):
        assert table in ('assets', 'requests', 'jobs')
        with self.connect() as c:
            row = c.execute(f'SELECT doc FROM {table} WHERE id=?', (oid,)).fetchone()
            if not row:
                raise HTTPException(404, '记录不存在')
            return json.loads(row['doc'])

    def put_doc(self, table, doc, project_id=None):
        assert table in ('assets', 'requests', 'jobs')
        with self.connect() as c:
            if table == 'assets':
                c.execute('INSERT INTO assets VALUES(?,?,?)', (doc['id'], project_id, json.dumps(doc)))
            else:
                c.execute(f'INSERT OR REPLACE INTO {table} VALUES(?,?)', (doc['id'], json.dumps(doc)))
        return doc

    def docs(self, table):
        assert table in ('assets', 'requests', 'jobs')
        with self.connect() as c:
            return [json.loads(r['doc']) for r in c.execute(f'SELECT doc FROM {table} ORDER BY rowid DESC')]

    def path(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise HTTPException(400, '路径越界')
        return path

    def atomic(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + '.' + uid() + '.tmp')
        temp.write_bytes(data)
        os.replace(temp, path)
