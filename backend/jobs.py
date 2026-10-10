import copy
import io
import json
import math
import zipfile
import threading
from concurrent.futures import ThreadPoolExecutor
from fastapi import HTTPException
from PIL import Image
from .models import uid
from .storage import now
from .imaging import png, render, duration, boundaries, validate, open_asset, add_asset, transform


class Jobs:
    def __init__(self,store):
        self.store=store
        self.pool=ThreadPoolExecutor(max_workers=1)

    def submit(self,kind,version,options,actor):
        job=dict(id=uid(),kind=kind,status='queued',progress=0,created_at=now(),version_id=version['id'],revision=version['revision'],options=options,result=None,error=None)
        self.store.put_doc('jobs',job)
        self.pool.submit(self.run,job,copy.deepcopy(version),actor)
        return job

    def progress(self,job,value):
        with self.store.lock:
            latest=self.store.doc('jobs',job['id'])
            if latest['status']=='cancelled':
                raise InterruptedError('任务已取消')
            job['progress']=value
            self.store.put_doc('jobs',job)

    def run(self,job,version,actor):
        try:
            job['status']='running'
            self.progress(job,1)
            result = self.export(job,version) if job['kind']=='export' else self.convert(job,version,actor)
            self.progress(job,100)
            job.update(status='completed',result=result)
        except InterruptedError as e:
            job.update(status='cancelled',error=str(e))
        except Exception as e:
            job.update(status='failed',error=str(e.detail if isinstance(e,HTTPException) else e))
        with self.store.lock:
            if self.store.doc('jobs',job['id'])['status']=='cancelled':
                job.update(status='cancelled',error='任务已取消')
            self.store.put_doc('jobs',job)

    def export(self,job,v):
        state=v['state']; opt=job['options']; end=duration(state)
        report=validate(self.store,v)
        fatal=[e for e in report['errors'] if '超出画布' not in e or not opt.get('allow_clip')]
        if fatal:
            raise ValueError('；'.join(fatal))
        points=boundaries(state)
        if opt.get('mode','union')=='fixed':
            count=int(opt.get('count',len(state['frames'])))
            if not 1 <= count <= 1000 or end < count:
                raise ValueError('固定帧数需为1至1000且不得超过毫秒时长')
            points=[round(i*end/count) for i in range(count+1)]
            report['warnings'].append('固定帧数按时间采样，可能遗漏特效变化；已记录目标时间点')
        count=len(points)-1
        if count>1000:
            raise ValueError('导出超过1000帧，请简化曝光或选择固定帧数')
        cw,ch=state['canvas']['width'],state['canvas']['height']
        cols=min(8,count)
        if cw*cols*ch*math.ceil(count/cols)>100_000_000:
            raise ValueError('图集超过100百万像素，请缩小画布或减少帧数')
        atlas=Image.new('RGBA',(cw*cols,ch*math.ceil(count/cols)))
        rel=f'projects/{v["project_id"]}/exports/{job["id"]}.zip'
        out=io.BytesIO(); entries=[]
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            for i,t in enumerate(points[:-1]):
                self.progress(job,5+int(85*i/max(1,count)))
                image=render(self.store,state,t,exporting=True)
                name=f'{v["action_id"][:8]}_{v["id"][:8]}_F{i+1:03}.png'
                z.writestr('frames/'+name,png(image))
                x,y=(i%cols)*cw,(i//cols)*ch
                atlas.alpha_composite(image,(x,y))
                entries.append(dict(file='frames/'+name,time_ms=t,duration_ms=points[i+1]-t,rect=[x,y,cw,ch]))
                if opt.get('layers'):
                    for track in state['tracks']:
                        if track['export'] and track['visible']:
                            z.writestr(f'layers/{track["id"]}/F{i+1:03}.png',png(render(self.store,state,t,exporting=True,track_id=track['id'])))
            manifest=dict(schema_version=1,version_id=v['id'],revision=v['revision'],action_id=v['action_id'],name=v['name'],
                          canvas=state['canvas'],body=state['body'],pivot_normalized=report['pivot_normalized'],mode=opt.get('mode','union'),frames=entries,
                          original_frames=state['frames'],tracks=state['tracks'],issues=state['issues'],prompt=state['prompt'])
            z.writestr('atlas.png',png(atlas))
            z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            z.writestr('validation.json',json.dumps(report,ensure_ascii=False,indent=2))
        self.progress(job,95)
        self.store.atomic(self.store.path(rel),out.getvalue())
        return dict(path=rel,frame_count=count,download_url=f'/api/v1/jobs/{job["id"]}/download',report=report)

    def convert(self,job,v,actor):
        state=v['state']; opt=job['options']; rect=opt['reference_rect']
        ratio=min(opt['target_width']/rect['width'],opt['target_height']/rect['height'])
        ids=set(opt.get('track_ids') or [t['id'] for t in state['tracks'] if t['kind']=='character'])
        if not ids:
            raise ValueError('没有可转换的图层')
        method=Image.Resampling.NEAREST if opt.get('method')=='nearest' else Image.Resampling.LANCZOS
        cache={}; exposures=[e for t in state['tracks'] if t['id'] in ids for e in t['exposures']]
        if not exposures:
            raise ValueError('选中图层没有素材')
        for i,e in enumerate(exposures):
            self.progress(job,5+int(75*i/len(exposures)))
            aid=e['asset_id']
            if aid in cache:
                e['asset_id']=cache[aid]['id']; continue
            image=open_asset(self.store,aid)
            image=image.resize((max(1,round(image.width*ratio)),max(1,round(image.height*ratio))),method)
            colors=opt.get('colors',0)
            if colors:
                alpha=image.getchannel('A')
                image=image.convert('RGB').quantize(colors=colors,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.FLOYDSTEINBERG if opt.get('dither') else Image.Dither.NONE).convert('RGBA')
                image.putalpha(alpha)
            asset=add_asset(self.store,v['project_id'],png(image),'精度转换-'+self.store.asset(aid)['name'],aid,'resize')
            cache[aid]=asset; e['asset_id']=asset['id']
        for track in state['tracks']:
            if track['id'] not in ids: continue
            base=track['transform']
            for key in ('anchor_x','anchor_y'):
                if base.get(key) is not None: base[key]*=ratio
            base['scale']=1
            for e in track['exposures']:
                tr=e.get('transform',{})
                for key in ('anchor_x','anchor_y'):
                    if tr.get(key) is not None: tr[key]*=ratio
                if 'scale' in tr: tr['scale']=1
        state['body'].update(width=opt['target_width'],height=opt['target_height'],reference_rect=dict(x=round(rect['x']*ratio),y=round(rect['y']*ratio),width=max(1,round(rect['width']*ratio)),height=max(1,round(rect['height']*ratio))))
        with self.store.lock:
            self.progress(job,95)
            updated=self.store.save(v['id'],v['revision'],state,actor,'convert')
        return dict(version_id=v['id'],revision=updated['revision'],scale=ratio,actual_body_size=[round(rect['width']*ratio),round(rect['height']*ratio)],assets=list(cache.values()))
