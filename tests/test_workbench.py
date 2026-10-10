import io
import json
import time
import zipfile
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.models import State,Frame,Track,Exposure,Transform
from backend.imaging import sample,boundaries,open_asset


@pytest.fixture
def bench(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as client:
        p=client.post('/api/v1/projects',json={'name':'测试项目'}).json()
        c=client.post('/api/v1/characters',json={'name':'测试角色','parent_id':p['id']}).json()
        a=client.post('/api/v1/actions',json={'name':'攻击','parent_id':c['id']}).json()
        v=client.post(f'/api/v1/actions/{a["id"]}/versions',json={'name':'v001'}).json()
        yield client,app,p,v
    app.state.jobs.pool.shutdown(wait=True)


def upload(client,p,color=(255,0,0,255),size=(4,4)):
    image=Image.new('RGBA',size,color);image.putpixel((0,0),(0,0,0,0))
    buf=io.BytesIO();image.save(buf,format='PNG')
    response=client.post('/api/v1/assets',data={'project_id':p['id']},files={'file':('sprite.png',buf.getvalue(),'image/png')})
    assert response.status_code==200,response.text
    return response.json()


def version(client,p,v,asset,frames=8):
    state=State(frames=[Frame(duration_ms=100) for _ in range(frames)],tracks=[Track(exposures=[Exposure(asset_id=asset['id'],duration_ms=100) for _ in range(frames)])]).model_dump()
    state['canvas'].update(width=32,height=32,pivot_x=16,pivot_y=28,ground_y=28)
    response=client.put(f'/api/v1/versions/{v["id"]}',json={'expected_revision':v['revision'],'state':state})
    assert response.status_code==200,response.text
    return response.json()


def wait_job(client,jid):
    for _ in range(200):
        j=client.get(f'/api/v1/jobs/{jid}').json()
        if j['status'] not in ('running','queued'): return j
        time.sleep(.01)
    pytest.fail('task timed out')


def test_cross_client_conflict_and_persistence(bench,tmp_path):
    client,app,p,v=bench;asset=upload(client,p);v=version(client,p,v,asset)
    state=v['state'];state['frames'][0]['events']=['damage']
    r=client.put(f'/api/v1/versions/{v["id"]}',json={'expected_revision':v['revision'],'state':state},headers={'X-Actor':'codex'})
    assert r.status_code==200
    assert client.put(f'/api/v1/versions/{v["id"]}',json={'expected_revision':v['revision'],'state':state}).status_code==409
    new=create_app(tmp_path)
    assert new.state.store.get_version(v['id'])['state']['frames'][0]['events']==['damage']
    assert client.get(f'/api/v1/versions/{v["id"]}/history').json()[0]['actor']=='codex'
    new.state.jobs.pool.shutdown()


def test_pixel_edit_forks_and_undo_redo(bench):
    client,app,p,v=bench;a=upload(client,p);v=version(client,p,v,a);t=v['state']['tracks'][0]
    patch={'expected_revision':v['revision'],'track_id':t['id'],'exposure_id':t['exposures'][0]['id'],'patches':[{'x':1,'y':1,'rgba':[0,255,0,255]}]}
    changed=client.post(f'/api/v1/versions/{v["id"]}/pixels',json=patch).json()
    exp=changed['state']['tracks'][0]['exposures']
    assert exp[0]['asset_id']!=a['id'] and exp[1]['asset_id']==a['id']
    assert open_asset(app.state.store,a['id']).getpixel((1,1))==(255,0,0,255)
    assert open_asset(app.state.store,exp[0]['asset_id']).getpixel((1,1))==(0,255,0,255)
    undone=client.post(f'/api/v1/versions/{v["id"]}/undo',json={'expected_revision':changed['revision']}).json()
    assert undone['state']['tracks'][0]['exposures'][0]['asset_id']==a['id']
    redone=client.post(f'/api/v1/versions/{v["id"]}/redo',json={'expected_revision':undone['revision']}).json()
    assert redone['state']['tracks'][0]['exposures'][0]['asset_id']==exp[0]['asset_id']


def test_eight_character_three_effect_time_mapping(bench):
    client,app,p,v=bench;a=upload(client,p);e=upload(client,p,(0,255,255,255));v=version(client,p,v,a)
    track=Track(name='特效',kind='effect',start_ms=300,exposures=[Exposure(asset_id=e['id'],duration_ms=100) for _ in range(3)]).model_dump()
    assert sample(track,299) is None
    assert sample(track,300)['id']==track['exposures'][0]['id']
    assert sample(track,500)['id']==track['exposures'][2]['id']
    assert sample(track,600) is None
    v['state']['tracks'].append(track)
    v=client.put(f'/api/v1/versions/{v["id"]}',json={'expected_revision':v['revision'],'state':v['state']}).json()
    im=Image.open(io.BytesIO(client.get(f'/api/v1/versions/{v["id"]}/render?time_ms=300').content))
    assert im.getpixel((15,26))==(0,255,255,255)
    im=Image.open(io.BytesIO(client.get(f'/api/v1/versions/{v["id"]}/render?time_ms=600').content))
    assert im.getpixel((15,26))==(255,0,0,255)


def test_loop_and_union_boundaries(bench):
    client,app,p,v=bench;a=upload(client,p);v=version(client,p,v,a,2)
    t=Track(kind='effect',end_behavior='loop',start_ms=25,exposures=[Exposure(asset_id=a['id'],duration_ms=30),Exposure(asset_id=a['id'],duration_ms=40)]).model_dump()
    v['state']['tracks'].append(t)
    assert sample(t,95)['id']==t['exposures'][0]['id']
    assert boundaries(v['state'])==[0,25,55,95,100,125,165,195,200]


def test_export_png_pivot_duration_layers(bench):
    client,app,p,v=bench;a=upload(client,p);v=version(client,p,v,a)
    job=client.post(f'/api/v1/versions/{v["id"]}/export',json={'expected_revision':v['revision'],'layers':True}).json()
    result=wait_job(client,job['id']);assert result['status']=='completed',result
    payload=client.get(result['result']['download_url']).content
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        manifest=json.loads(z.read('manifest.json'))
        assert manifest['canvas']['pivot_x']==16
        assert len(manifest['frames'])==8
        assert sum(f['duration_ms'] for f in manifest['frames'])==800
        im=Image.open(io.BytesIO(z.read(manifest['frames'][0]['file'])))
        assert im.size==(32,32) and im.mode=='RGBA'
        assert im.getpixel((0,0))[3]==0
        assert any(n.startswith('layers/') for n in z.namelist())


def test_export_fixed_with_subframe_effect(bench):
    client,app,p,v=bench;a=upload(client,p);v=version(client,p,v,a,2)
    v['state']['tracks'].append(Track(kind='effect',start_ms=25,exposures=[Exposure(asset_id=a['id'],duration_ms=30)]).model_dump())
    v=client.put(f'/api/v1/versions/{v["id"]}',json={'expected_revision':v['revision'],'state':v['state']}).json()
    for mode,expected in [('union',4),('fixed',2)]:
        j=client.post(f'/api/v1/versions/{v["id"]}/export',json={'expected_revision':v['revision'],'mode':mode,'count':2}).json()
        result=wait_job(client,j['id']);assert result['status']=='completed',result
        assert result['result']['frame_count']==expected


def test_clipping_blocks_without_opt_in(bench):
    client,app,p,v=bench;a=upload(client,p);v=version(client,p,v,a);v['state']['tracks'][0]['transform']['dx']=100
    v=client.put(f'/api/v1/versions/{v["id"]}',json={'expected_revision':v['revision'],'state':v['state']}).json()
    report=client.get(f'/api/v1/versions/{v["id"]}/validate').json();assert len(report['clipping'])==8
    j=client.post(f'/api/v1/versions/{v["id"]}/export',json={'expected_revision':v['revision']}).json()
    assert wait_job(client,j['id'])['status']=='failed'


def test_conversion_same_ratio_preserves_source_and_alpha(bench):
    client,app,p,v=bench;a=upload(client,p,size=(40,100));v=version(client,p,v,a)
    j=client.post(f'/api/v1/versions/{v["id"]}/convert',json={'expected_revision':v['revision'],'reference_rect':{'x':0,'y':0,'width':40,'height':100},'target_width':20,'target_height':50,'colors':8}).json()
    result=wait_job(client,j['id']);assert result['status']=='completed',result
    updated=client.get(f'/api/v1/versions/{v["id"]}').json();aid=updated['state']['tracks'][0]['exposures'][0]['asset_id']
    assert open_asset(app.state.store,a['id']).size==(40,100)
    assert open_asset(app.state.store,aid).size==(20,50)
    assert updated['state']['canvas']['width']==32
    assert result['result']['actual_body_size']==[20,50]


def test_generation_snapshot_idempotent_and_claim_conflict(bench):
    client,app,p,v=bench;a=upload(client,p);v=version(client,p,v,a);v['state']['prompt']['final_text']='原始提示词';v['state']['prompt']['reference_ids']=[a['id']]
    v=client.put(f'/api/v1/versions/{v["id"]}',json={'expected_revision':v['revision'],'state':v['state']}).json()
    req=client.post('/api/v1/generation-requests',json={'version_id':v['id'],'expected_revision':v['revision']}).json()
    v['state']['prompt']['final_text']='后续修改'
    client.put(f'/api/v1/versions/{v["id"]}',json={'expected_revision':v['revision'],'state':v['state']})
    assert client.get('/api/v1/generation-requests').json()[0]['snapshot']['prompt']['final_text']=='原始提示词'
    assert client.post(f'/api/v1/generation-requests/{req["id"]}/claim',headers={'X-Actor':'codex'}).status_code==200
    assert client.post(f'/api/v1/generation-requests/{req["id"]}/claim',headers={'X-Actor':'other'}).status_code==409
    for _ in range(2): assert client.post(f'/api/v1/generation-requests/{req["id"]}/complete',json={'asset_ids':[a['id']]}).status_code==200


def test_stable_frame_identity_after_reorder_and_clone(bench):
    client,app,p,v=bench;a=upload(client,p);v=version(client,p,v,a)
    first=v['state']['frames'][0]['id']
    v['state']['issues']=[dict(id='i',frame_id=first,track_id=None,rect=None,tag='武器',note='剑柄',status='open',author='user',original_label='F001')]
    v['state']['frames'].reverse()
    v=client.put(f'/api/v1/versions/{v["id"]}',json={'expected_revision':v['revision'],'state':v['state']}).json()
    clone=client.post(f'/api/v1/versions/{v["id"]}/clone',json={'expected_revision':v['revision'],'state':v['state'],'name':'v002'}).json()
    assert clone['state']['frames'][-1]['id']==first
    assert clone['state']['issues'][0]['frame_id']==first
    assert clone['state']['issues'][0]['status']=='recheck'


def test_slice_validation_and_edge_warnings(bench):
    client,app,p,v=bench;a=upload(client,p,size=(8,8))
    result=client.post(f'/api/v1/assets/{a["id"]}/slice',json={'columns':2,'rows':2}).json()
    assert len(result['assets'])==4 and len(result['warnings'])==4
    assert client.post(f'/api/v1/assets/{a["id"]}/slice',json={'rects':[{'x':7,'y':7,'width':4,'height':4}]}).status_code==422


def test_local_origin_and_backup(bench):
    client,app,p,v=bench;a=upload(client,p)
    assert client.post('/api/v1/projects',json={'name':'bad'},headers={'Origin':'https://example.com'}).status_code==403
    b=client.post('/api/v1/backup').json();r=client.get(b['download_url']);assert r.status_code==200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert 'workspace.sqlite' in z.namelist() and app.state.store.asset(a['id'])['path'] in z.namelist()


def test_reference_layer_excluded_from_export(bench):
    client,app,p,v=bench;a=upload(client,p);e=upload(client,p,(0,255,0,255));v=version(client,p,v,a)
    v['state']['tracks'].append(Track(kind='reference',export=False,exposures=[Exposure(asset_id=e['id'])]).model_dump())
    from backend.imaging import render
    assert render(app.state.store,v['state'],0).getpixel((15,26))==(0,255,0,255)
    assert render(app.state.store,v['state'],0,exporting=True).getpixel((15,26))==(255,0,0,255)


def test_bad_pivot_and_foreign_asset_rejected(bench):
    client,app,p,v=bench;a=upload(client,p);v=version(client,p,v,a)
    v['state']['canvas']['pivot_x']=40
    assert client.put(f'/api/v1/versions/{v["id"]}',json={'expected_revision':v['revision'],'state':v['state']}).status_code==422
    v['state']['canvas']['pivot_x']=16
    p2=client.post('/api/v1/projects',json={'name':'other'}).json();a2=upload(client,p2)
    v['state']['tracks'][0]['exposures'][0]['asset_id']=a2['id']
    assert client.put(f'/api/v1/versions/{v["id"]}',json={'expected_revision':v['revision'],'state':v['state']}).status_code==422


def test_anchor_flip_and_opacity(bench):
    client,app,p,v=bench;a=upload(client,p);v=version(client,p,v,a)
    t=v['state']['tracks'][0]
    t['transform'].update(anchor_x=0,anchor_y=0,flip_x=True,dx=0,dy=0,opacity=.5)
    from backend.imaging import render
    im=render(app.state.store,v['state'],0)
    assert im.getpixel((14,29))==(255,0,0,128)
    assert im.getpixel((17,29))[3]==0


def test_restart_marks_jobs_interrupted(bench,tmp_path):
    client,app,p,v=bench
    app.state.store.put_doc('jobs',{'id':'unfinished','status':'running','progress':50})
    fresh=create_app(tmp_path)
    assert fresh.state.store.doc('jobs','unfinished')['status']=='interrupted'
    fresh.state.jobs.pool.shutdown()
