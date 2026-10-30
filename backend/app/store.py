import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


def fail(status, message, code=None, details=None):
    raise HTTPException(status, {"detail": message, "code": code, "details": details or {}})


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class Store:
    def __init__(self, directory):
        self.path = Path(directory).resolve()
        self.path.mkdir(parents=True, exist_ok=True)
        self.images = self.path / "images"
        self.images.mkdir(exist_ok=True)
        self.db = self.path / "workbench.sqlite3"
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("CREATE TABLE IF NOT EXISTS objects(kind TEXT NOT NULL,id TEXT PRIMARY KEY,data TEXT NOT NULL)")
            c.execute("CREATE INDEX IF NOT EXISTS object_kind ON objects(kind)")

    def connect(self):
        c = sqlite3.connect(self.db, timeout=30, factory=ClosingConnection)
        c.row_factory = sqlite3.Row
        return c

    @contextmanager
    def transaction(self):
        c = self.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def get(self, kind, key, c=None):
        if c is None:
            with self.connect() as connection:
                return self.get(kind, key, connection)
        row = c.execute("SELECT data FROM objects WHERE kind=? AND id=?", (kind, key)).fetchone()
        if not row:
            fail(404, f"找不到 {kind}: {key}", "not_found")
        return json.loads(row["data"])

    def all(self, kind, c=None):
        if c is None:
            with self.connect() as connection:
                return self.all(kind, connection)
        return [json.loads(row[0]) for row in c.execute("SELECT data FROM objects WHERE kind=? ORDER BY rowid", (kind,))]

    def put(self, kind, value, c):
        c.execute("INSERT INTO objects(kind,id,data) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (kind, value["id"], json.dumps(value, ensure_ascii=False)))
        return value
