"""Import the user's existing study as an explicitly unaccepted example."""
import sys
from pathlib import Path
from fastapi.testclient import TestClient
from backend.app import app
from backend.models import State,Frame,Track,Exposure,Transform,Issue,uid

def main():
    source=Path(sys.argv[1])
    with TestClient(app) as client:
        cat=client.get('/api/v1/catalog').json()
        if any(o['name']=='长剑试稿 · 检查演示' for o in cat['objects']):
            print('示例已存在，跳过');return
        p=client.post('/api/v1/projects',json={'name':'长剑试稿 · 检查演示'}).json()
        c=client.post('/api/v1/characters',json={'name':'黑金兜帽少女','parent_id':p['id']}).json()
        a=client.post('/api/v1/actions',json={'name':'长剑斜斩 · 8帧试稿','parent_id':c['id']}).json()
        v=client.post(f'/api/v1/actions/{a["id"]}/versions',json={'name':'v001 · 原始试稿'}).json()
        asset=client.post('/api/v1/assets',data={'project_id':p['id']},files={'file':(source.name,source.read_bytes(),'image/png')}).json()
        sliced=client.post(f'/api/v1/assets/{asset["id"]}/slice',json={'columns':4,'rows':2}).json()
        assert 'assets' in sliced,sliced
        frames=[Frame(duration_ms=100) for _ in range(8)]
        frames[4].events=['damage'];frames[3].events=['trail-start']
        for index in (3,4,5,7):frames[index].status='problem'
        t=Track(name='角色与剑光 · 原图合在一起',transform=Transform(scale=.45),exposures=[Exposure(asset_id=a['id'],duration_ms=100) for a in sliced['assets']])
        state=State(frames=frames,tracks=[t]).model_dump()
        state['canvas'].update(width=256,height=256,pivot_x=128,pivot_y=235,ground_y=235)
        state['body'].update(width=70,height=180)
        state['prompt'].update(identity='黑色短发、金色眼睛、黑金兜帽与裙装；蓝色符文长剑；没有盾牌。',motion='朝右方斜向下挥斩后收回。',frame_notes='F001待机；F002蓄力；F003举剑；F004加速；F005命中；F006随势；F007回收；F008待机。',reference_ids=[asset['id']],changes='检查长剑方向、帧间衔接、首尾姿势、切片边界。原始图集有跨格问题，不是已验收素材。')
        for idx,note in [(3,'举剑到挥动的角度衔接需要复查。'),(4,'剑光与剑尖可能伸入相邻格，规则切片仅用于暴露问题。'),(5,'检查是否混入前一格的剑尖、剑光。'),(7,'与F001首尾姿势不完全一致，需要校准。')]:
            state['issues'].append(Issue(frame_id=frames[idx].id,track_id=t.id,tag='衔接' if idx in (3,7) else '裁切',note=note,original_label=f'F{idx+1:03}').model_dump())
        result=client.put(f'/api/v1/versions/{v["id"]}',json={'expected_revision':v['revision'],'state':state},headers={'X-Actor':'codex'}).json()
        assert 'revision' in result,result
        print(result['id'])

if __name__=='__main__':main()
