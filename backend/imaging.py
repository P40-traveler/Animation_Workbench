import io
import math
import hashlib
from PIL import Image, ImageDraw, ImageFont
from fastapi import HTTPException
from .models import uid, Transform
from .storage import now

Image.MAX_IMAGE_PIXELS = 32_000_000


def png(image):
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def add_asset(store, project_id, data, name, parent=None, operation='import', original=False):
    store.object(project_id, 'project')
    try:
        im = Image.open(io.BytesIO(data))
        if im.format != 'PNG' or im.width * im.height > 32_000_000:
            raise ValueError('仅支持32百万像素以内的 PNG')
        im.load()
        image = im.convert('RGBA')
    except Exception as e:
        raise HTTPException(422, f'图片读取失败：{e}')
    aid = uid()
    rel = f'projects/{project_id}/{"sources" if original else "derived"}/{aid}.png'
    payload = data if original else png(image)
    store.atomic(store.path(rel), payload)
    alpha = image.getchannel('A')
    doc = dict(id=aid, project_id=project_id, name=name, width=image.width, height=image.height,
               has_alpha=('A' in im.getbands() or 'transparency' in im.info), alpha_range=list(alpha.getextrema()),
               transparent_pixels=alpha.histogram()[0], bbox=alpha.getbbox(), parent_id=parent,
               operation=operation, path=rel, sha256=hashlib.sha256(payload).hexdigest(), created_at=now())
    return store.put_doc('assets', doc, project_id)


def open_asset(store, aid):
    with Image.open(store.path(store.asset(aid)['path'])) as im:
        return im.convert('RGBA')


def duration(state):
    return sum(f['duration_ms'] for f in state['frames'])


def frame_at(state, time_ms):
    at = 0
    for i, f in enumerate(state['frames']):
        if at <= time_ms < at + f['duration_ms']:
            return i, f
        at += f['duration_ms']
    return None, None


def sample(track, time_ms):
    exposures = track['exposures']
    total = sum(e['duration_ms'] for e in exposures)
    local = time_ms - track['start_ms']
    if not exposures or total == 0 or local < 0:
        return None
    if local >= total:
        if track['end_behavior'] == 'hide':
            return None
        if track['end_behavior'] == 'hold':
            return exposures[-1]
        local %= total
    at = 0
    for e in exposures:
        if local < at + e['duration_ms']:
            return e
        at += e['duration_ms']
    return None


def transform(track, exposure):
    return Transform.model_validate({**track['transform'], **exposure.get('transform', {})}).model_dump()


def matrix(tr, image, canvas):
    ax = image.width / 2 if tr['anchor_x'] is None else tr['anchor_x']
    ay = image.height if tr['anchor_y'] is None else tr['anchor_y']
    theta = math.radians(tr['rotation'])
    sx = tr['scale'] * (-1 if tr['flip_x'] else 1)
    sy = tr['scale'] * (-1 if tr['flip_y'] else 1)
    a, b, c, d = math.cos(theta)*sx, -math.sin(theta)*sy, math.sin(theta)*sx, math.cos(theta)*sy
    tx = canvas['pivot_x'] + tr['dx'] - a*ax - b*ay
    ty = canvas['pivot_y'] + tr['dy'] - c*ax - d*ay
    return a, b, c, d, tx, ty


def bounds(store, track, exp, canvas):
    im = open_asset(store, exp['asset_id'])
    bbox = im.getchannel('A').getbbox()
    if bbox is None:
        return None
    a, b, c, d, tx, ty = matrix(transform(track, exp), im, canvas)
    points = [(a*x+b*y+tx, c*x+d*y+ty) for x, y in [(bbox[0],bbox[1]),(bbox[2],bbox[1]),(bbox[0],bbox[3]),(bbox[2],bbox[3])]]
    return [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]


def render(store, state, time_ms, exporting=False, track_id=None):
    cv = state['canvas']
    out = Image.new('RGBA', (cv['width'], cv['height']))
    for track in state['tracks']:
        if not track['visible'] or (exporting and not track['export']) or (track_id and track['id'] != track_id):
            continue
        exp = sample(track, time_ms)
        if not exp:
            continue
        im = open_asset(store, exp['asset_id'])
        tr = transform(track, exp)
        a, b, c, d, tx, ty = matrix(tr, im, cv)
        det = a*d - b*c
        inverse = (d/det, -b/det, (b*ty-d*tx)/det, -c/det, a/det, (c*tx-a*ty)/det)
        layer = im.transform(out.size, Image.Transform.AFFINE, inverse, resample=Image.Resampling.NEAREST)
        if tr['opacity'] != 1:
            layer.putalpha(layer.getchannel('A').point(lambda p: round(p*tr['opacity'])))
        out = Image.alpha_composite(out, layer)
    return out


def boundaries(state):
    end = duration(state)
    points = {0, end}
    t = 0
    for f in state['frames']:
        t += f['duration_ms']
        points.add(t)
    for track in state['tracks']:
        if not track['visible'] or not track['export']:
            continue
        total = sum(e['duration_ms'] for e in track['exposures'])
        if not total:
            continue
        start = track['start_ms']
        while start < end:
            points.add(start)
            t = start
            for e in track['exposures']:
                t += e['duration_ms']
                points.add(t)
            if track['end_behavior'] != 'loop':
                break
            start += total
            if len(points) > 5000:
                raise HTTPException(422, '曝光边界超过5000，请降低动画复杂度')
    return sorted(p for p in points if 0 <= p <= end)


def validate(store, version):
    state = version['state']
    cv = state['canvas']
    warnings, errors = [], []
    if not state['frames']:
        errors.append('没有动作帧')
    if not any(t['visible'] and t['export'] and t['exposures'] for t in state['tracks']):
        errors.append('没有可导出的图层素材')
    clipping = []
    for t in state['tracks']:
        for i, e in enumerate(t['exposures']):
            try:
                asset = store.asset(e['asset_id'])
                if not asset['transparent_pixels']:
                    warnings.append(f'{t["name"]} E{i+1:03} 没有完全透明像素，请检查背景')
                if t['export'] and t['visible']:
                    bound = bounds(store,t,e,cv)
                    if bound and (bound[0] < -0.01 or bound[1] < -0.01 or bound[2] > cv['width']+.01 or bound[3] > cv['height']+.01):
                        clipping.append(dict(track_id=t['id'], exposure_id=e['id'], bounds=bound))
            except HTTPException:
                errors.append(f'{t["name"]} E{i+1:03} 素材缺失')
    if clipping:
        errors.append(f'{len(clipping)}个曝光的可见内容超出画布；正式导出会阻止裁切')
    outstanding = sum(i['status'] != 'resolved' for i in state['issues'])
    if outstanding:
        warnings.append(f'{outstanding}条人工问题尚未解决或待复查；格式通过不代表动作已验收')
    for track in state['tracks']:
        if track['kind']=='character' and len(track['exposures']) != len(state['frames']):
            warnings.append(f'{track["name"]} 的素材帧数与动作帧数不同，请检查是否有意设置独立时序')
    point_names = set(k for f in state['frames'] for k in f['points'])
    movement = {}
    for key in point_names:
        sequence = [f['points'].get(key) for f in state['frames']]
        movement[key] = sequence
        present = [p for p in sequence if p and len(p)==2]
        if len(present)>1 and any(p != present[0] for p in present):
            warnings.append(f'参考点 {key} 在帧间发生移动，检查是否为有意位移')
    return dict(version_id=version['id'], revision=version['revision'], canvas=cv,
                pivot_normalized=[cv['pivot_x']/cv['width'],cv['pivot_y']/cv['height']],
                frame_count=len(state['frames']), duration_ms=duration(state),
                errors=errors,warnings=list(dict.fromkeys(warnings)),clipping=clipping,points=movement)


def onion(store,state,time_ms,before=1,after=1,opacity=.25,track_id=None):
    i, _ = frame_at(state,time_ms)
    if i is None:
        return render(store,state,time_ms,track_id=track_id)
    times, at = [], 0
    for f in state['frames']:
        times.append(at)
        at += f['duration_ms']
    result = Image.new('RGBA',(state['canvas']['width'],state['canvas']['height']))
    for j in range(max(0,i-before),min(len(times),i+after+1)):
        if j==i:
            continue
        layer = render(store,state,times[j],track_id=track_id)
        colored = Image.new('RGBA',layer.size,(255,90,120) if j<i else (90,170,255))
        colored.putalpha(layer.getchannel('A').point(lambda p: round(p*opacity)))
        result=Image.alpha_composite(result,colored)
    return Image.alpha_composite(result,render(store,state,time_ms,track_id=track_id))


def contact(store,state):
    n = len(state['frames'])
    if not n:
        raise HTTPException(422,'没有帧')
    thumb = min(160,state['canvas']['width'])
    height = round(state['canvas']['height'] * thumb / state['canvas']['width'])
    columns = min(8,n)
    out = Image.new('RGBA',(columns*(thumb+12),math.ceil(n/columns)*(height+32)),(24,29,39,255))
    draw = ImageDraw.Draw(out)
    time = 0
    for i,f in enumerate(state['frames']):
        image=render(store,state,time)
        image=image.resize((thumb,height),Image.Resampling.NEAREST)
        x,y=(i%columns)*(thumb+12), (i//columns)*(height+32)
        out.alpha_composite(image,(x,y))
        draw.text((x,y+height+4),f'F{i+1:03} {f["duration_ms"]}ms',fill='white')
        time+=f['duration_ms']
    return out
