"""Exercise the public API in an isolated data directory; never touches user assets."""

import base64
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid
import zipfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


class Client:
    def __init__(self, port):
        self.url = f"http://127.0.0.1:{port}"
        self.passed = []

    def call(self, method, path, payload=None, status=200, binary=False):
        data = None if payload is None else json.dumps(payload).encode()
        req = Request(self.url + path, data=data, method=method,
                      headers={"Content-Type": "application/json"} if data is not None else {})
        try:
            response = urlopen(req, timeout=30)
        except HTTPError as exc:
            body = exc.read()
            assert exc.code == status, (method, path, exc.code, body.decode(errors="replace"))
            return json.loads(body)
        with response:
            body = response.read()
            assert response.status == status or (status == 200 and response.status == 201), (path, response.status)
        return body if binary else json.loads(body)

    def ok(self, label):
        self.passed.append(label)
        print("PASS", label, flush=True)


def exercise(client):
    client.call("GET", "/api/health")
    project = client.call("POST", "/api/projects", {"name": "隔离 API 验收"})
    workspace = client.call("POST", f"/api/projects/{project['id']}/demo", {})
    action = next(a for a in workspace["actions"] if a["kind"] == "attack")
    revision = next(r for r in workspace["revisions"] if r["id"] == action["current_revision_id"])
    assert client.call("GET", f"/api/revisions/{revision['id']}/checks")["passed"]
    client.ok("demo assets satisfy their declared format")

    frame_id = revision["frames"][2]["id"]
    issue = client.call("POST", f"/api/actions/{action['id']}/issues", {
        "revision_id": revision["id"], "frame_id": frame_id,
        "layer_id": "character", "rect": {"x": 10, "y": 10, "width": 2, "height": 2},
        "category": "weapon", "message": "核验稳定帧身份",
    })
    task = client.call("POST", f"/api/actions/{action['id']}/tasks", {
        "base_revision_id": revision["id"], "kind": "generate", "instruction": "接口验收候选",
    })
    bundle = client.call("GET", f"/api/tasks/{task['id']}/bundle")
    assert bundle["base_revision"]["id"] == revision["id"]
    assert bundle["task"]["spec_snapshot"] == revision["spec"]
    client.ok("task bundle freezes the confirmed specification")

    frames = list(revision["frames"])
    frames[0], frames[2] = frames[2], frames[0]
    edited = client.call("POST", f"/api/actions/{action['id']}/revisions", {
        "base_revision_id": revision["id"], "label": "重排验收", "frames": frames,
    })["revision"]
    client.call("POST", f"/api/actions/{action['id']}/revisions", {
        "base_revision_id": revision["id"], "label": "不应覆盖",
    }, status=409)
    result_payload = {
        "base_revision_id": revision["id"], "label": "基于旧版本的候选",
        "frames": revision["frames"], "effects": revision["effects"],
        "events": revision["events"], "submission_id": "verify-once",
    }
    submitted = client.call("POST", f"/api/tasks/{task['id']}/result", result_payload)
    repeated = client.call("POST", f"/api/tasks/{task['id']}/result", result_payload)
    assert repeated["revision"]["id"] == submitted["revision"]["id"]
    client.call("POST", f"/api/actions/{action['id']}/adopt", {
        "revision_id": submitted["revision"]["id"], "expected_current_revision_id": revision["id"],
    }, status=409)
    workspace = client.call("GET", f"/api/projects/{project['id']}/workspace")
    assert next(a for a in workspace["actions"] if a["id"] == action["id"])["current_revision_id"] == edited["id"]
    assert next(i for i in workspace["issues"] if i["id"] == issue["id"])["frame_id"] == frame_id
    assert edited["frames"][0]["id"] == frame_id
    client.ok("reordering preserves issue identity; stale commits cannot overwrite; result retry is idempotent")

    original = client.call("GET", f"/api/images/{edited['frames'][0]['image_id']}", binary=True)
    image = Image.open(io.BytesIO(original)).convert("RGBA")
    image.putpixel((10, 10), (255, 0, 255, 255))
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    upload = client.call("POST", "/api/images", {"filename": "local-patch.png", "source": "edit",
        "data_base64": base64.b64encode(encoded.getvalue()).decode()})
    repair = client.call("POST", f"/api/actions/{action['id']}/tasks", {
        "base_revision_id": edited["id"], "kind": "repair", "instruction": "仅修改指定区域",
        "allowed_frame_ids": [frame_id], "allowed_rect": {"x": 10, "y": 10, "width": 2, "height": 2},
    })
    patched_frames = [dict(f) for f in edited["frames"]]
    patched_frames[0]["image_id"] = upload["id"]
    repair_payload = {"base_revision_id": edited["id"], "label": "合法区域修补", "frames": patched_frames}
    repaired = client.call("POST", f"/api/tasks/{repair['id']}/result", repair_payload)
    assert repaired["revision"]["frames"][0]["image_id"] == upload["id"]
    outside_task = client.call("POST", f"/api/actions/{action['id']}/tasks", {
        "base_revision_id": edited["id"], "kind": "repair", "instruction": "拒绝越界修改",
        "allowed_frame_ids": [frame_id], "allowed_rect": {"x": 20, "y": 20, "width": 2, "height": 2},
    })
    client.call("POST", f"/api/tasks/{outside_task['id']}/result", repair_payload, status=422)
    client.ok("repair accepts in-scope pixels and rejects out-of-scope edits")

    effect = dict(revision["effects"][0])
    effect.update({"id": str(uuid.uuid4()), "name": "20ms 特效验收", "image_ids": effect["image_ids"][:1],
                   "durations_ms": [20], "start_ms": 250, "visible": True})
    uniform_frames = [dict(f, duration_ms=100) for f in edited["frames"]]
    timed = client.call("POST", f"/api/actions/{action['id']}/revisions", {
        "base_revision_id": edited["id"], "label": "短特效时间验收", "frames": uniform_frames,
        "effects": [effect], "events": [],
    })["revision"]
    fixed = client.call("GET", f"/api/revisions/{timed['id']}/export-preview?mode=fixed&layers=composite")
    preserved = client.call("GET", f"/api/revisions/{timed['id']}/export-preview?mode=preserve&layers=composite")
    assert fixed["requires_loss_ack"]
    assert preserved["frame_count"] > fixed["frame_count"]
    client.call("GET", f"/api/revisions/{timed['id']}/export?mode=fixed&layers=composite&draft=true", status=409)
    client.ok("fixed export reports short-effect loss; preserve mode retains all exposure boundaries")

    client.call("POST", f"/api/revisions/{timed['id']}/review", {"status": "accepted"})
    archive = client.call("GET", f"/api/revisions/{timed['id']}/export?mode=preserve&layers=composite", binary=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        assert "manifest.json" in zf.namelist()
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest
        png_names = [name for name in zf.namelist() if name.startswith("frames/") and name.endswith(".png")]
        assert len(png_names) == preserved["frame_count"]
        for index, name in enumerate(sorted(png_names)):
            exported_image = Image.open(io.BytesIO(zf.read(name))).convert("RGBA")
            assert exported_image.size == (timed["spec"]["canvas_width"], timed["spec"]["canvas_height"])
            sample = preserved["samples"][index]
            rendered = client.call("GET", f"/api/revisions/{timed['id']}/render?time_ms={sample['time_ms']}&layer=composite", binary=True)
            assert exported_image.tobytes() == Image.open(io.BytesIO(rendered)).convert("RGBA").tobytes()
    client.ok("exported PNGs match the public render API pixel-for-pixel")

    scaled = client.call("POST", f"/api/revisions/{timed['id']}/scale", {
        "base_revision_id": timed["id"], "scale": 0.5,
        "canvas_width": timed["spec"]["canvas_width"] // 2,
        "canvas_height": timed["spec"]["canvas_height"] // 2, "label": "统一缩放验收",
    })["revision"]
    assert len(scaled["frames"]) == len(timed["frames"])
    assert scaled["spec"]["pivot_x"] == round(timed["spec"]["pivot_x"] * 0.5)
    assert client.call("GET", f"/api/images/{edited['frames'][0]['image_id']}", binary=True) == original
    client.ok("uniform scaling creates a derived version and preserves original images")
    return project["id"], scaled["id"]


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    runtime_dir = (ROOT / "runtime").resolve()
    if runtime_dir.parent != ROOT:
        raise RuntimeError("Verification directory must remain within the workspace")
    runtime_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="verify-", dir=runtime_dir) as data_dir:
        if Path(data_dir).resolve().parent != runtime_dir:
            raise RuntimeError("Temporary verification directory escaped the workspace")
        env = os.environ.copy()
        env["WORKBENCH_DATA_DIR"] = str(Path(data_dir) / "data")
        log_path = Path(data_dir) / "server.log"
        args = [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(ROOT / "backend"),
                "--host", "127.0.0.1", "--port", str(port)]
        client = Client(port)

        def start(log):
            process = subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Backend exited during startup")
                try:
                    client.call("GET", "/api/health")
                    return process
                except (URLError, OSError):
                    time.sleep(0.1)
            process.terminate()
            process.wait(timeout=10)
            raise RuntimeError("Backend startup timed out")

        process = None
        try:
            with log_path.open("w", encoding="utf-8") as log:
                process = start(log)
                project_id, current_revision_id = exercise(client)
                process.terminate()
                process.wait(timeout=10)
                process = start(log)
                reloaded = client.call("GET", f"/api/projects/{project_id}/workspace")
                assert any(a["current_revision_id"] == current_revision_id for a in reloaded["actions"])
                client.ok("server restart preserves the workspace and current revision")
                print(json.dumps({"passed": len(client.passed), "checks": client.passed}, ensure_ascii=False, indent=2))
        except Exception:
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            if log_path.exists():
                print(log_path.read_text(encoding="utf-8", errors="replace"), file=sys.stderr)
            raise
        finally:
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    main()
