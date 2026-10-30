import base64
import binascii
import io
import json
import math
import warnings
import zipfile

from PIL import Image, ImageChops

from .store import fail, uid

MAX_IMAGE_PIXELS = 4096 * 4096
MAX_EXPORT_PIXELS = 64 * 1024 * 1024


def png_bytes(image):
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def save_image(store, image, filename, source, c):
    if image.width > 4096 or image.height > 4096 or image.width * image.height > MAX_IMAGE_PIXELS:
        fail(422, "图片超过 4096×4096 上限", "image_limit")
    ident = uid()
    image.convert("RGBA").save(store.images / f"{ident}.png", format="PNG")
    return store.put("image", {"id": ident, "url": f"/api/images/{ident}", "width": image.width, "height": image.height, "filename": filename, "source": source}, c)


def upload(store, body, c):
    value = body.data_base64
    if value.startswith("data:"):
        try:
            header, value = value.split(",", 1)
        except ValueError:
            fail(422, "图片 data URL 无效")
        if not header.startswith("data:image/") or ";base64" not in header:
            fail(422, "只接受 base64 图片 data URL")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        fail(422, "图片 base64 无效")
    if len(raw) > 20 * 1024 * 1024:
        fail(413, "单张上传不可超过 20MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.width > 4096 or image.height > 4096 or image.width * image.height > MAX_IMAGE_PIXELS:
                    fail(422, "图片超过 4096×4096 上限")
                image.load()
                return save_image(store, image, body.filename, body.source, c)
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        fail(422, "无法解码图片")


def load_image(store, image_id, c=None):
    store.get("image", image_id, c)
    path = store.images / f"{image_id}.png"
    if not path.is_file():
        fail(422, "图片文件缺失", "missing_image", {"image_id": image_id})
    with Image.open(path) as image:
        return image.convert("RGBA")


def total_time(revision):
    return sum(f["duration_ms"] for f in revision["frames"])


def frame_at(frames, time_ms):
    cursor = 0
    for frame in frames:
        if cursor <= time_ms < cursor + frame["duration_ms"]:
            return frame
        cursor += frame["duration_ms"]
    return None


def effect_image_at(effect, time_ms):
    cursor = effect["start_ms"]
    if not effect["visible"] or effect["opacity"] == 0:
        return None
    for image_id, duration in zip(effect["image_ids"], effect["durations_ms"]):
        if cursor <= time_ms < cursor + duration:
            return image_id
        cursor += duration
    return None


def composite_image(canvas, image, x, y, opacity=1):
    if opacity != 1:
        image = image.copy()
        image.putalpha(image.getchannel("A").point(lambda a: round(a * opacity)))
    canvas.alpha_composite(image, (x, y))


def render(store, revision, time_ms, layer="composite", c=None):
    spec = revision["spec"]
    canvas = Image.new("RGBA", (spec["canvas_width"], spec["canvas_height"]))
    total = total_time(revision)
    if total == 0:
        return canvas
    time_ms = min(time_ms, total - 1)

    def effects(z):
        for effect in revision["effects"]:
            if effect["z"] != z:
                continue
            image_id = effect_image_at(effect, time_ms)
            if image_id:
                composite_image(canvas, load_image(store, image_id, c), effect["x"], effect["y"], effect["opacity"])

    if layer in ("composite", "effects"):
        effects("back")
    if layer in ("composite", "character"):
        frame = frame_at(revision["frames"], time_ms)
        if frame:
            composite_image(canvas, load_image(store, frame["image_id"], c), frame["offset_x"], frame["offset_y"])
    if layer in ("composite", "effects"):
        effects("front")
    return canvas


def checks(store, revision, c=None):
    errors, notices = [], []
    spec = revision["spec"]
    width, height = spec["canvas_width"], spec["canvas_height"]
    if len(revision["frames"]) != spec["target_frame_count"]:
        errors.append({"code": "frame_count", "message": f"目标 {spec['target_frame_count']} 帧，实际 {len(revision['frames'])} 帧"})
    if total_time(revision) > 120000:
        errors.append({"code": "duration", "message": "动作总时长超过 120000ms"})

    def inspect(image_id, x, y, frame_id=None, is_character=False):
        tag = {"frame_id": frame_id} if frame_id else {}
        try:
            image = load_image(store, image_id, c)
        except Exception as exc:
            from fastapi import HTTPException
            if not isinstance(exc, (HTTPException, OSError)):
                raise
            errors.append({"code": "missing_image", "message": "图片无法读取", **tag})
            return
        if is_character and image.size != (width, height):
            errors.append({"code": "canvas_size", "message": f"角色图片 {image.width}×{image.height} 与画布 {width}×{height} 不同", **tag})
        alpha = image.getchannel("A")
        bounds = alpha.getbbox()
        lo, hi = alpha.getextrema()
        if lo == 255:
            notices.append({"code": "opaque", "message": "图片没有透明像素，请人工确认背景", **tag})
        if hi == 0:
            notices.append({"code": "empty", "message": "图片完全透明", **tag})
        if bounds:
            left, top, right, bottom = bounds
            if left + x < 0 or top + y < 0 or right + x > width or bottom + y > height:
                errors.append({"code": "out_of_bounds", "message": "可见像素经过位置变换后超出画布", **tag})
            elif left + x == 0 or top + y == 0 or right + x == width or bottom + y == height:
                notices.append({"code": "touching_edge", "message": "内容触及画布边缘，请检查裁切", **tag})
    for f in revision["frames"]:
        inspect(f["image_id"], f["offset_x"], f["offset_y"], f["id"], True)
    for effect in revision["effects"]:
        for image_id in effect["image_ids"]:
            inspect(image_id, effect["x"], effect["y"])
    frames = {f["id"]: f for f in revision["frames"]}
    for event in revision["events"]:
        if event["frame_id"] not in frames or event["offset_ms"] >= frames[event["frame_id"]]["duration_ms"]:
            errors.append({"code": "event_range", "message": f"事件 {event['name']} 未绑定有效帧内时刻", "frame_id": event["frame_id"]})
    return {"passed": not errors, "errors": errors, "warnings": notices}


def export_preview(revision, mode, layers):
    total = total_time(revision)
    boundaries = {0, total}
    cursor = 0
    for frame in revision["frames"]:
        cursor += frame["duration_ms"]
        boundaries.add(cursor)
    character_boundaries = set(boundaries)
    for effect in revision["effects"]:
        if not effect["visible"] or effect["opacity"] == 0:
            continue
        cursor = effect["start_ms"]
        if 0 < cursor < total:
            boundaries.add(cursor)
        for duration in effect["durations_ms"]:
            cursor += duration
            if 0 < cursor < total:
                boundaries.add(cursor)
    loss = mode == "fixed" and layers == "composite" and bool(boundaries - character_boundaries)
    points = sorted(character_boundaries if mode == "fixed" or layers == "separate" else boundaries)
    samples = [{"time_ms": t, "duration_ms": end - t} for t, end in zip(points, points[1:])]
    notices = [{"code": "effect_timing_loss", "message": "固定帧只在角色帧起点采样，帧内特效变化将被遗漏；请明确接受或选择保留全部时序。"}] if loss else []
    return {"mode": mode, "layers": layers, "frame_count": len(samples), "duration_ms": total, "samples": samples, "warnings": notices, "requires_loss_ack": loss}


def export_zip(store, revision, mode, layers, draft):
    preview = export_preview(revision, mode, layers)
    spec = revision["spec"]
    width, height = spec["canvas_width"], spec["canvas_height"]
    frame_count = len(preview["samples"])
    if layers == "separate":
        frame_count += sum(len(e["image_ids"]) for e in revision["effects"])
    if frame_count * width * height > MAX_EXPORT_PIXELS or frame_count > 8192:
        fail(422, "导出累计像素超过 64M 或帧数超过 8192；请缩小画布或拆分动作", "export_limit")
    out = io.BytesIO()
    manifest = {"format_version": "0.1.0", "revision_id": revision["id"], "action_id": revision["action_id"], "review_status": revision["review_status"], "draft": draft, "canvas_width": width, "canvas_height": height, "pivot": {"x": spec["pivot_x"], "y": spec["pivot_y"]}, **preview, "events": [], "effects": revision["effects"], "source_frames": revision["frames"], "layers_metadata": []}
    starts, cursor = {}, 0
    for f in revision["frames"]:
        starts[f["id"]] = cursor
        cursor += f["duration_ms"]
    manifest["events"] = [{**event, "time_ms": starts[event["frame_id"]] + event["offset_ms"]} for event in revision["events"]]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        def write_sequence(images, timings, prefix, metadata):
            count = len(images)
            if not count:
                return
            cols = min(16, max(1, math.ceil(math.sqrt(count))))
            rows = math.ceil(count / cols)
            if cols * width > 16384 or rows * height > 16384:
                fail(422, "图集单边超过 16384 像素", "export_limit")
            atlas = Image.new("RGBA", (cols * width, rows * height))
            entries = []
            for index, (image, timing) in enumerate(zip(images, timings)):
                filename = f"{prefix}frames/F{index + 1:03d}.png"
                data = png_bytes(image)
                # Read-back verifies encoded size/mode before packaging.
                with Image.open(io.BytesIO(data)) as decoded:
                    decoded.load()
                    if decoded.size != (width, height) or decoded.mode != "RGBA":
                        fail(500, "导出回读校验失败")
                archive.writestr(filename, data)
                x, y = index % cols * width, index // cols * height
                atlas.paste(image, (x, y))
                entries.append({"file": filename, **timing, "atlas_rect": {"x": x, "y": y, "width": width, "height": height}})
            archive.writestr(f"{prefix}spritesheet.png", png_bytes(atlas))
            manifest["layers_metadata"].append({**metadata, "frames": entries, "spritesheet": f"{prefix}spritesheet.png"})
        if layers == "composite":
            write_sequence([render(store, revision, s["time_ms"]) for s in preview["samples"]], preview["samples"], "", {"id": "composite"})
        else:
            # Character and effects are rendered into fixed canvas cells, so positions and opacity are baked.
            write_sequence([render(store, revision, s["time_ms"], "character") for s in preview["samples"]], preview["samples"], "character/", {"id": "character", "transforms_baked": True})
            for index, effect in enumerate(revision["effects"]):
                images, timings, cursor = [], [], effect["start_ms"]
                for image_id, duration in zip(effect["image_ids"], effect["durations_ms"]):
                    canvas = Image.new("RGBA", (width, height))
                    composite_image(canvas, load_image(store, image_id), effect["x"], effect["y"], effect["opacity"])
                    images.append(canvas)
                    timings.append({"time_ms": cursor, "duration_ms": duration, "image_id": image_id})
                    cursor += duration
                write_sequence(images, timings, f"effects/{index + 1:02d}/", {"id": effect["id"], "z": effect["z"], "visible": effect["visible"], "transforms_baked": True})
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(io.BytesIO(out.getvalue())) as archive:
        saved = json.loads(archive.read("manifest.json"))
        if saved["revision_id"] != revision["id"] or saved["duration_ms"] != total_time(revision) or archive.testzip():
            fail(500, "导出包回读校验失败")
    return out.getvalue()


def repair_allowed(store, task, base, candidate, c):
    if candidate["effects"] != base["effects"] or candidate["events"] != base["events"]:
        fail(422, "局部返工不可修改特效或事件", "scope_violation")
    old, new = base["frames"], candidate["frames"]
    if len(old) != len(new):
        fail(422, "局部返工不可增删帧", "scope_violation")
    allowed = set(task["allowed_frame_ids"])
    for a, b in zip(old, new):
        if {k: v for k, v in a.items() if k != "image_id"} != {k: v for k, v in b.items() if k != "image_id"}:
            fail(422, "局部返工不可改变帧序、时长或偏移", "scope_violation")
        if a["image_id"] == b["image_id"]:
            continue
        if a["id"] not in allowed:
            fail(422, "修改了未授权的帧", "scope_violation", {"frame_id": a["id"]})
        original, replacement = load_image(store, a["image_id"], c), load_image(store, b["image_id"], c)
        if original.size != replacement.size:
            fail(422, "局部返工必须保持图片尺寸", "scope_violation")
        rect = task["allowed_rect"]
        if rect:
            diff = ImageChops.difference(original, replacement)
            from PIL import ImageDraw
            ImageDraw.Draw(diff).rectangle((rect["x"], rect["y"], rect["x"] + rect["width"] - 1, rect["y"] + rect["height"] - 1), fill=(0, 0, 0, 0))
            if any(channel.getbbox() for channel in diff.split()):
                fail(422, "修改了授权矩形以外的像素", "scope_violation", {"frame_id": a["id"]})
