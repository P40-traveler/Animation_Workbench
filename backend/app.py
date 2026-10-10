import copy
import io
import json
import os
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Query
from fastapi.responses import Response, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image
from .models import State, VersionWrite, Revision, Rect, uid
from .storage import Store, now
from .imaging import add_asset, open_asset, png, render, onion, contact, validate
from .jobs import Jobs

ROOT=Path(__file__).resolve().parents[1]


class Create(BaseModel):
    name: str = Field(min_length=1,max_length=120)
    parent_id: str | None = None


class Slice(BaseModel):
    rects: list[Rect] | None = None
    columns: int = Field(default=1,ge=1,le=100)
    rows: int = Field(default=1,ge=1,le=100)
    width: int | None = Field(default=None,gt=0)
    height: int | None = Field(default=None,gt=0)
    margin: int = Field(default=0,ge=0)
    spacing: int = Field(default=0,ge=0)
    order: str = 'row'


class PixelPatch(BaseModel):
    x: int
    y: int
    rgba: list[int] = Field(min_length=4,max_length=4)


class Pixels(Revision):
    track_id: str
    exposure_id: str
    patches: list[PixelPatch] = Field(max_length=250000)


class Convert(Revision):
    track_ids: list[str] = []
    reference_rect: Rect
    target_width: int = Field(gt=0,le=2048)
    target_height: int = Field(gt=0,le=2048)
    method: str = 'nearest'
    colors: int = Field(default=0,ge=0,le=256)
    dither: bool = False


class Export(Revision):
    mode: str = 'union'
    count: int = Field(default=8,ge=1,le=1000)
    allow_clip: bool = False
    layers: bool = False


class Generation(Revision):
    version_id: str


class Complete(BaseModel):
    asset_ids: list[str]
    note: str = ''


def create_app(data_dir=None):
    store=Store(data_dir or os.getenv('AW_DATA_DIR',str(ROOT/'data')))
    jobs=Jobs(store)
    app=FastAPI(title='帧间 · 动画素材工作台',version='1.0.0')
    app.state.store=store; app.state.jobs=jobs

    @app.middleware('http')
    async def local_only(request:Request,call_next):
        host=request.headers.get('host','').split(':')[0]
        if host not in ('127.0.0.1','localhost','testserver'):
            return JSONResponse({'detail':'仅允许本地访问'},status_code=403)
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin=request.headers.get('origin')
            if origin and urlparse(origin).netloc != request.headers.get('host'):
                # Development Vite uses port 5173 and forwards the Host unchanged.
                if origin not in ('http://127.0.0.1:5173','http://localhost:5173'):
                    return JSONResponse({'detail':'请求来源不匹配'},status_code=403)
        return await call_next(request)

    def actor(request):
        return request.headers.get('x-actor','user')[:100]

    def revision(vid,expected):
        v=store.get_version(vid)
        if v['revision']!=expected:
            raise HTTPException(409,'版本已变化，请刷新后重试')
        return v

    @app.get('/api/v1/health')
    def health():
        return dict(status='ok',version='1.0.0',data_dir=str(store.root))

    @app.get('/api/v1/catalog')
    def catalog():
        with store.connect() as c:
            return dict(objects=[dict(r) for r in c.execute('SELECT * FROM objects')],versions=[dict(r) for r in c.execute('SELECT id,action_id,name,revision FROM versions')])

    @app.post('/api/v1/projects')
    def project(body:Create): return store.create('project',None,body.name)

    @app.post('/api/v1/characters')
    def character(body:Create):
        if not body.parent_id: raise HTTPException(422,'缺少项目ID')
        return store.create('character',body.parent_id,body.name)

    @app.post('/api/v1/actions')
    def action(body:Create):
        if not body.parent_id: raise HTTPException(422,'缺少角色ID')
        return store.create('action',body.parent_id,body.name)

    @app.post('/api/v1/actions/{aid}/versions')
    def new(aid:str,body:Create): return store.new_version(aid,body.name)

    @app.get('/api/v1/versions/{vid}')
    def get(vid:str): return store.get_version(vid)

    @app.put('/api/v1/versions/{vid}')
    def save(vid:str,body:VersionWrite,request:Request):
        return store.save(vid,body.expected_revision,body.state.model_dump(),actor(request),name=body.name)

    @app.post('/api/v1/versions/{vid}/clone')
    def clone(vid:str,body:VersionWrite,request:Request):
        v=revision(vid,body.expected_revision)
        state=body.state.model_dump()
        state['status']='draft'
        for issue in state['issues']: issue['status']='recheck'
        return store.new_version(v['action_id'],body.name or v['name']+' 副本',state)

    @app.post('/api/v1/versions/{vid}/undo')
    def undo(vid:str,body:Revision,request:Request): return store.travel(vid,body.expected_revision,'undo',actor(request))

    @app.post('/api/v1/versions/{vid}/redo')
    def redo(vid:str,body:Revision,request:Request): return store.travel(vid,body.expected_revision,'redo',actor(request))

    @app.get('/api/v1/versions/{vid}/history')
    def history(vid:str):
        store.get_version(vid)
        with store.connect() as c: return [dict(r) for r in c.execute('SELECT * FROM history WHERE version_id=? ORDER BY id DESC',(vid,))]

    @app.post('/api/v1/assets')
    async def upload(project_id:str=Form(...),file:UploadFile=File(...)):
        data=await file.read(64*1024*1024+1)
        if len(data)>64*1024*1024: raise HTTPException(413,'图片超过64MB')
        return add_asset(store,project_id,data,Path(file.filename or '素材.png').name,original=True)

    @app.get('/api/v1/assets')
    def assets(project_id:str):
        store.object(project_id,'project')
        return [a for a in store.docs('assets') if a['project_id']==project_id]

    @app.get('/api/v1/assets/{aid}/image')
    def image(aid:str): return FileResponse(store.path(store.asset(aid)['path']),media_type='image/png')

    @app.post('/api/v1/assets/{aid}/slice')
    def slicing(aid:str,body:Slice):
        asset=store.asset(aid); im=open_asset(store,aid)
        rects=body.rects
        if rects is None:
            w=body.width or (im.width-2*body.margin-(body.columns-1)*body.spacing)//body.columns
            h=body.height or (im.height-2*body.margin-(body.rows-1)*body.spacing)//body.rows
            if w<1 or h<1: raise HTTPException(422,'切片格尺寸无效')
            rects=[Rect(x=body.margin+c*(w+body.spacing),y=body.margin+r*(h+body.spacing),width=w,height=h) for r in range(body.rows) for c in range(body.columns)]
            if body.order=='column': rects.sort(key=lambda r:(r.x,r.y))
        if not rects or len(rects)>1000: raise HTTPException(422,'切片数量必须为1至1000')
        for r in rects:
            if r.x<0 or r.y<0 or r.x+r.width>im.width or r.y+r.height>im.height:
                raise HTTPException(422,'切片框超出原图')
        result=[]; warnings=[]
        for i,r in enumerate(rects):
            cut=im.crop((r.x,r.y,r.x+r.width,r.y+r.height))
            a=cut.getchannel('A')
            edge=max(a.crop((0,0,cut.width,1)).getextrema()[1],a.crop((0,cut.height-1,cut.width,cut.height)).getextrema()[1],a.crop((0,0,1,cut.height)).getextrema()[1],a.crop((cut.width-1,0,cut.width,cut.height)).getextrema()[1])
            if edge>0: warnings.append(f'F{i+1:03} 边界有非透明像素，请检查是否跨格')
            result.append(add_asset(store,asset['project_id'],png(cut),f'{asset["name"]}-F{i+1:03}',aid,'slice'))
        return dict(assets=result,warnings=warnings)

    @app.get('/api/v1/versions/{vid}/render')
    def rendering(vid:str,time_ms:int=Query(0,ge=0),track_id:str|None=None):
        return Response(png(render(store,store.get_version(vid)['state'],time_ms,track_id=track_id)),media_type='image/png')

    @app.get('/api/v1/versions/{vid}/onion')
    def onioning(vid:str,time_ms:int=Query(0,ge=0),before:int=Query(1,ge=0,le=5),after:int=Query(1,ge=0,le=5),opacity:float=Query(.25,ge=0,le=1),track_id:str|None=None):
        return Response(png(onion(store,store.get_version(vid)['state'],time_ms,before,after,opacity,track_id)),media_type='image/png')

    @app.get('/api/v1/versions/{vid}/contact-sheet')
    def contacting(vid:str): return Response(png(contact(store,store.get_version(vid)['state'])),media_type='image/png')

    @app.get('/api/v1/versions/{vid}/region')
    def region(vid:str,x:int,y:int,width:int=Query(gt=0,le=2048),height:int=Query(gt=0,le=2048),time_ms:int=0):
        return Response(png(render(store,store.get_version(vid)['state'],time_ms).crop((x,y,x+width,y+height))),media_type='image/png')

    @app.get('/api/v1/versions/{vid}/validate')
    def validating(vid:str): return validate(store,store.get_version(vid))

    @app.post('/api/v1/versions/{vid}/pixels')
    def pixels(vid:str,body:Pixels,request:Request):
        v=revision(vid,body.expected_revision)
        track=next((t for t in v['state']['tracks'] if t['id']==body.track_id),None)
        if not track or track['locked']: raise HTTPException(422,'图层不存在或已锁定')
        exp=next((e for e in track['exposures'] if e['id']==body.exposure_id),None)
        if not exp: raise HTTPException(422,'曝光不存在')
        im=open_asset(store,exp['asset_id'])
        for p in body.patches:
            if not (0<=p.x<im.width and 0<=p.y<im.height) or any(c<0 or c>255 for c in p.rgba):
                raise HTTPException(422,'像素坐标或颜色无效')
            im.putpixel((p.x,p.y),tuple(p.rgba))
        asset=add_asset(store,v['project_id'],png(im),'像素修订-'+store.asset(exp['asset_id'])['name'],exp['asset_id'],'pixel-patch')
        exp['asset_id']=asset['id']
        return store.save(vid,body.expected_revision,v['state'],actor(request),'pixels')

    @app.post('/api/v1/versions/{vid}/convert')
    def convert(vid:str,body:Convert,request:Request):
        if body.method not in ('nearest','smooth') or body.colors==1: raise HTTPException(422,'转换参数无效')
        return jobs.submit('convert',revision(vid,body.expected_revision),body.model_dump(),actor(request))

    @app.post('/api/v1/versions/{vid}/export')
    def export(vid:str,body:Export,request:Request):
        if body.mode not in ('union','fixed'): raise HTTPException(422,'导出模式无效')
        return jobs.submit('export',revision(vid,body.expected_revision),body.model_dump(),actor(request))

    @app.get('/api/v1/jobs')
    def job_list(): return store.docs('jobs')

    @app.get('/api/v1/jobs/{jid}')
    def job_get(jid:str): return store.doc('jobs',jid)

    @app.post('/api/v1/jobs/{jid}/cancel')
    def cancel(jid:str):
        with store.lock:
            j=store.doc('jobs',jid)
            if j['status'] in ('queued','running'): j['status']='cancelled'; store.put_doc('jobs',j)
        return j

    @app.get('/api/v1/jobs/{jid}/download')
    def download(jid:str):
        j=store.doc('jobs',jid)
        if j['status']!='completed' or not j.get('result',{}).get('path'): raise HTTPException(422,'任务没有可下载的结果')
        return FileResponse(store.path(j['result']['path']),filename=f'animation-{jid[:8]}.zip')

    @app.post('/api/v1/generation-requests')
    def generation(body:Generation):
        v=revision(body.version_id,body.expected_revision)
        if not v['state']['prompt']['final_text'].strip(): raise HTTPException(422,'请先保存最终提示词')
        doc=dict(id=uid(),version_id=v['id'],revision=v['revision'],project_id=v['project_id'],status='pending',
                 snapshot=copy.deepcopy(v['state']),created_at=now(),asset_ids=[],note='')
        return store.put_doc('requests',doc)

    @app.get('/api/v1/generation-requests')
    def requests_list(): return store.docs('requests')

    @app.post('/api/v1/generation-requests/{rid}/claim')
    def claim(rid:str,request:Request):
        with store.lock:
            doc=store.doc('requests',rid)
            who=actor(request)
            if doc['status']=='claimed' and doc.get('claimed_by')==who: return doc
            if doc['status']!='pending': raise HTTPException(409,'请求已被领取或结束')
            doc.update(status='claimed',claimed_by=who)
            return store.put_doc('requests',doc)

    @app.post('/api/v1/generation-requests/{rid}/complete')
    def complete(rid:str,body:Complete):
        with store.lock:
            doc=store.doc('requests',rid)
            if doc['status']=='completed':
                if doc['asset_ids']==body.asset_ids: return doc
                raise HTTPException(409,'已回传不同结果，请创建新请求')
            if doc['status'] not in ('pending','claimed'): raise HTTPException(409,'请求已结束')
            for aid in body.asset_ids:
                if store.asset(aid)['project_id']!=doc['project_id']: raise HTTPException(422,'结果项目不匹配')
            if not body.asset_ids: raise HTTPException(422,'缺少结果素材')
            doc.update(status='completed',asset_ids=body.asset_ids,note=body.note,completed_at=now())
            return store.put_doc('requests',doc)

    @app.post('/api/v1/generation-requests/{rid}/status')
    def request_status(rid:str,body:dict):
        with store.lock:
            doc=store.doc('requests',rid)
            if doc['status']=='completed': raise HTTPException(409,'已完成请求不能改状态')
            if body.get('status') not in ('cancelled','failed'): raise HTTPException(422,'仅支持取消或失败')
            doc.update(status=body['status'],note=str(body.get('note','')))
            return store.put_doc('requests',doc)

    @app.post('/api/v1/backup')
    def backup():
        bid=uid(); path=store.path(f'backups/{bid}.zip')
        payload=io.BytesIO()
        with store.lock:
            dbtemp=store.path(f'backups/{bid}.sqlite')
            dbtemp.parent.mkdir(parents=True,exist_ok=True)
            with store.connect() as connection:
                with closing(sqlite3.connect(dbtemp)) as dst: connection.backup(dst)
            with zipfile.ZipFile(payload,'w',zipfile.ZIP_DEFLATED) as z:
                z.write(dbtemp,'workspace.sqlite')
                for source in (store.root/'projects').rglob('*'):
                    if source.is_file(): z.write(source,source.relative_to(store.root).as_posix())
            dbtemp.unlink()
            store.atomic(path,payload.getvalue())
        return dict(id=bid,download_url=f'/api/v1/backups/{bid}/download')

    @app.get('/api/v1/backups/{bid}/download')
    def backup_download(bid:str):
        if len(bid)!=32 or any(c not in '0123456789abcdef' for c in bid): raise HTTPException(400,'ID无效')
        path=store.path(f'backups/{bid}.zip')
        if not path.is_file(): raise HTTPException(404,'备份不存在')
        return FileResponse(path,filename=f'workbench-backup-{bid[:8]}.zip')

    dist=ROOT/'frontend'/'dist'
    if dist.exists(): app.mount('/',StaticFiles(directory=dist,html=True),name='frontend')
    return app


app=create_app()
