import base64
from concurrent.futures import ThreadPoolExecutor
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Avoid module-level app initialization touching a real workspace during tests.
_temp_root = Path(__file__).resolve().parents[1] / ".test-data"
_temp_root.mkdir(exist_ok=True)
_import_data = tempfile.TemporaryDirectory(prefix="import-", dir=_temp_root)
os.environ.setdefault("WORKBENCH_DATA_DIR", _import_data.name)
from app.main import create_app


@pytest.fixture
def setup(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "test"}).json()
    ws = client.post(f"/api/projects/{project['id']}/demo", json={}).json()
    action = next(a for a in ws["actions"] if a["kind"] == "attack")
    revision = next(r for r in ws["revisions"] if r["id"] == action["current_revision_id"])
    return client, project, action, revision, tmp_path


def uploaded(client, image):
    buf = io.BytesIO()
    image.save(buf, "PNG")
    response = client.post("/api/images", json={"filename": "test.png", "data_base64": base64.b64encode(buf.getvalue()).decode(), "source": "edit"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def save(client, action, base, **payload):
    return client.post(f"/api/actions/{action['id']}/revisions", json={"base_revision_id": base["id"], "label": "test", **payload})


def test_concurrent_writes_only_one_wins(setup):
    client, project, action, revision, path = setup
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda label: save(client, action, revision, label=label), ["one", "two"]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    ws = client.get(f"/api/projects/{project['id']}/workspace").json()
    current = next(a for a in ws["actions"] if a["id"] == action["id"])
    assert current["current_revision_id"] == next(r for r in responses if r.status_code == 200).json()["revision"]["id"]
    reloaded = TestClient(create_app(path)).get(f"/api/projects/{project['id']}/workspace").json()
    assert reloaded["actions"] == ws["actions"]


def test_reorder_marks_stable_ids_and_events(setup):
    client, project, action, revision, _ = setup
    frame = revision["frames"][3]
    issue = client.post(f"/api/actions/{action['id']}/issues", json={"revision_id": revision["id"], "frame_id": frame["id"], "layer_id": "character", "category": "weapon", "message": "check"}).json()
    frames = revision["frames"].copy()
    frames.insert(0, frames.pop(3))
    result = save(client, action, revision, frames=frames)
    assert result.status_code == 200, result.text
    new = result.json()["revision"]
    assert new["events"][0]["frame_id"] == frame["id"]
    ws = client.get(f"/api/projects/{project['id']}/workspace").json()
    inherited = next(i for i in ws["issues"] if i["revision_id"] == new["id"])
    assert inherited["frame_id"] == issue["frame_id"]
    assert inherited["status"] == "open"
    deleted = save(client, action, new, frames=frames[1:])
    assert deleted.status_code == 422


def test_effect_boundaries_export_loss_and_pixel_consistency(setup):
    client, _, action, revision, _ = setup
    solid = Image.new("RGBA", (128, 128))
    solid.putpixel((10, 10), (255, 10, 20, 128))
    image_id = uploaded(client, solid)
    effect = {**revision["effects"][0], "image_ids": [image_id], "durations_ms": [20], "start_ms": 250, "opacity": 1}
    response = save(client, action, revision, effects=[effect])
    assert response.status_code == 200, response.text
    new = response.json()["revision"]
    prefix = f"/api/revisions/{new['id']}"
    for time, expected in [(249, (0, 0, 0, 0)), (250, (255, 10, 20, 128)), (269, (255, 10, 20, 128)), (270, (0, 0, 0, 0))]:
        raw = client.get(prefix + f"/render?time_ms={time}&layer=effects").content
        assert Image.open(io.BytesIO(raw)).getpixel((10, 10)) == expected
    fixed = client.get(prefix + "/export-preview?mode=fixed").json()
    preserve = client.get(prefix + "/export-preview?mode=preserve").json()
    assert fixed["requires_loss_ack"] and fixed["frame_count"] == 8
    assert preserve["frame_count"] == 10
    assert client.get(prefix + "/export?mode=fixed&draft=true").status_code == 409
    assert client.get(prefix + "/export?mode=preserve").status_code == 409
    assert client.post(prefix + "/review", json={"status": "accepted"}).status_code == 200
    exported = client.get(prefix + "/export?mode=preserve")
    assert exported.status_code == 200, exported.text[:100] if exported.status_code != 200 else ""
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["revision_id"] == new["id"]
        assert sum(s["duration_ms"] for s in manifest["samples"]) == 800
        for index, sample in enumerate(preserve["samples"]):
            png = Image.open(io.BytesIO(archive.read(f"frames/F{index+1:03d}.png")))
            rendered = Image.open(io.BytesIO(client.get(prefix + f"/render?time_ms={sample['time_ms']}").content))
            assert png.tobytes() == rendered.tobytes()
    separate = client.get(prefix + "/export-preview?mode=fixed&layers=separate").json()
    assert not separate["requires_loss_ack"]
    with zipfile.ZipFile(io.BytesIO(client.get(prefix + "/export?mode=fixed&layers=separate").content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        fx = next(layer for layer in manifest["layers_metadata"] if layer["id"] == effect["id"])
        assert fx["frames"][0]["time_ms"] == 250
        assert fx["frames"][0]["duration_ms"] == 20


def test_repair_checks_rgb_even_when_alpha_unchanged_and_idempotency(setup):
    client, _, action, revision, _ = setup
    frame = revision["frames"][0]
    image = Image.open(io.BytesIO(client.get(f"/api/images/{frame['image_id']}").content)).convert("RGBA")
    original = image.copy()
    task = client.post(f"/api/actions/{action['id']}/tasks", json={"base_revision_id": revision["id"], "kind": "repair", "allowed_frame_ids": [frame["id"]], "allowed_rect": {"x": 54, "y": 55, "width": 2, "height": 2}}).json()
    image.putpixel((60, 60), (255, 0, 0, 255))
    frames = copy.deepcopy(revision["frames"])
    frames[0]["image_id"] = uploaded(client, image)
    body = {"base_revision_id": revision["id"], "label": "repair", "frames": frames, "submission_id": "s1"}
    assert client.post(f"/api/tasks/{task['id']}/result", json=body).status_code == 422
    original.putpixel((54, 55), (255, 0, 0, 255))
    frames[0]["image_id"] = uploaded(client, original)
    body["frames"] = frames
    result = client.post(f"/api/tasks/{task['id']}/result", json=body)
    assert result.status_code == 200, result.text
    repeated = client.post(f"/api/tasks/{task['id']}/result", json=body)
    assert repeated.json()["revision"]["id"] == result.json()["revision"]["id"]
    changed = copy.deepcopy(body)
    changed["label"] = "different"
    assert client.post(f"/api/tasks/{task['id']}/result", json=changed).status_code == 409


def test_formats_and_input_limits(setup):
    client, _, action, revision, _ = setup
    assert client.post("/api/images", json={"filename": "bad", "data_base64": "notbase64"}).status_code == 422
    assert client.get(f"/api/revisions/{revision['id']}/render?time_ms=-1").status_code == 422
    mismatch = uploaded(client, Image.new("RGBA", (5, 5), (255, 0, 0, 255)))
    frames = copy.deepcopy(revision["frames"])
    frames[0]["image_id"] = mismatch
    result = save(client, action, revision, frames=frames).json()["revision"]
    report = client.get(f"/api/revisions/{result['id']}/checks").json()
    assert not report["passed"]
    assert "canvas_size" in {e["code"] for e in report["errors"]}
    assert client.post(f"/api/revisions/{result['id']}/review", json={"status": "accepted"}).status_code == 422
    assert save(client, action, result, frames=[frames[0], frames[0]]).status_code == 422


def test_task_snapshot_and_uniform_scale_keep_originals(setup):
    client, project, action, revision, path = setup
    task = client.post(f"/api/actions/{action['id']}/tasks", json={"base_revision_id": revision["id"], "kind": "generate", "instruction": "generate"}).json()
    original_image = client.get(f"/api/images/{revision['frames'][0]['image_id']}").content
    scaled = client.post(f"/api/revisions/{revision['id']}/scale", json={"base_revision_id": revision["id"], "scale": 0.5, "canvas_width": 64, "canvas_height": 64, "label": "scaled"})
    assert scaled.status_code == 200, scaled.text
    new = scaled.json()["revision"]
    assert new["spec"]["pivot_x"] == 32 and new["spec"]["pivot_y"] == 56
    assert client.get(f"/api/revisions/{new['id']}/checks").json()["passed"]
    assert client.get(f"/api/images/{revision['frames'][0]['image_id']}").content == original_image
    bundle = client.get(f"/api/tasks/{task['id']}/bundle").json()
    assert bundle["task"]["spec_snapshot"]["canvas_width"] == 128
    result = client.post(f"/api/tasks/{task['id']}/result", json={"base_revision_id": revision["id"], "frames": revision["frames"]})
    assert result.status_code == 200
    ws = client.get(f"/api/projects/{project['id']}/workspace").json()
    assert next(a for a in ws["actions"] if a["id"] == action["id"])["current_revision_id"] == new["id"]


def test_history_adoption_creates_new_revision_and_scale_drops_stale_rect(setup):
    client, project, action, original, _ = setup
    client.post(f"/api/actions/{action['id']}/issues", json={"revision_id": original["id"], "frame_id": original["frames"][0]["id"], "layer_id": "character", "rect": {"x": 10, "y": 10, "width": 2, "height": 2}, "category": "pixel", "message": "recheck"})
    edited = save(client, action, original, label="edit").json()["revision"]
    adopted = client.post(f"/api/actions/{action['id']}/adopt", json={"revision_id": original["id"], "expected_current_revision_id": edited["id"]})
    assert adopted.status_code == 200
    restored_id = adopted.json()["current_revision_id"]
    assert restored_id not in (original["id"], edited["id"])
    ws = client.get(f"/api/projects/{project['id']}/workspace").json()
    restored = next(r for r in ws["revisions"] if r["id"] == restored_id)
    assert restored["parent_revision_id"] == edited["id"]
    assert restored["frames"] == original["frames"]
    assert restored["review_status"] == "unreviewed"
    scaled = client.post(f"/api/revisions/{restored_id}/scale", json={"base_revision_id": restored_id, "scale": 0.5, "canvas_width": 64, "canvas_height": 64}).json()["revision"]
    ws = client.get(f"/api/projects/{project['id']}/workspace").json()
    issue = next(i for i in ws["issues"] if i["revision_id"] == scaled["id"])
    assert issue["rect"] is None
    assert issue["status"] == "needs_review"
    assert restored_id in issue["message"]


def test_first_candidate_adoption_and_cancelled_task(setup):
    client, _, action, original, _ = setup
    candidate = save(client, action, original, mode="candidate", author="agent").json()["revision"]
    adopted = client.post(f"/api/actions/{action['id']}/adopt", json={"revision_id": candidate["id"], "expected_current_revision_id": original["id"]})
    assert adopted.status_code == 200
    assert adopted.json()["current_revision_id"] == candidate["id"]
    task = client.post(f"/api/actions/{action['id']}/tasks", json={"base_revision_id": candidate["id"], "kind": "generate"}).json()
    assert client.patch(f"/api/tasks/{task['id']}", json={"status": "cancelled"}).status_code == 200
    assert client.patch(f"/api/tasks/{task['id']}", json={"status": "running"}).status_code == 409
    assert client.post(f"/api/tasks/{task['id']}/result", json={"base_revision_id": candidate["id"], "frames": candidate["frames"]}).status_code == 409


def test_task_boundary_context_is_frozen_and_loop_neighbors_wrap(setup):
    client, project, action, revision, path = setup
    task = client.post(f"/api/actions/{action['id']}/tasks", json={"base_revision_id": revision["id"], "kind": "repair", "allowed_frame_ids": [revision["frames"][0]["id"]]}).json()
    bundle = client.get(f"/api/tasks/{task['id']}/bundle").json()
    assert revision["frames"][-1]["id"] in {f["id"] for f in bundle["context"]["neighbor_frames"]}
    boundary = next(b for b in bundle["context"]["boundary_context"] if b["kind"] == "idle_transition")
    assert boundary["entry_frame"]["image_id"] in {i["id"] for i in bundle["images"]}
    assert boundary["exit_frame"]["image_id"] in {i["id"] for i in bundle["images"]}
    ws = client.get(f"/api/projects/{project['id']}/workspace").json()
    idle = next(a for a in ws["actions"] if a["id"] == boundary["action_id"])
    idle_revision = next(r for r in ws["revisions"] if r["id"] == idle["current_revision_id"])
    updated = save(client, idle, idle_revision, frames=list(reversed(idle_revision["frames"])))
    assert updated.status_code == 200
    reloaded = TestClient(create_app(path))
    later_bundle = reloaded.get(f"/api/tasks/{task['id']}/bundle").json()
    assert later_bundle["context"]["boundary_context"] == bundle["context"]["boundary_context"]
    assert next(b for b in later_bundle["context"]["boundary_context"] if b["kind"] == "idle_transition")["revision_id"] == idle_revision["id"]
    # The last frame also receives the first frame as its neighbor.
    tail_task = client.post(f"/api/actions/{action['id']}/tasks", json={"base_revision_id": revision["id"], "kind": "repair", "allowed_frame_ids": [revision["frames"][-1]["id"]]}).json()
    tail = client.get(f"/api/tasks/{tail_task['id']}/bundle").json()
    assert revision["frames"][0]["id"] in {f["id"] for f in tail["context"]["neighbor_frames"]}


@pytest.mark.parametrize("assignment", ["frame_count=12", "帧数:12", "canvas=64x128", "画布：128×64"])
def test_task_rejects_explicit_numeric_spec_conflict(setup, assignment):
    client, _, action, revision, _ = setup
    response = client.post(f"/api/actions/{action['id']}/tasks", json={"base_revision_id": revision["id"], "kind": "generate", "instruction": assignment})
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "explicit_spec_conflict"


def test_task_accepts_matching_assignments_and_prose_but_checks_prompt(setup):
    client, _, action, revision, _ = setup
    response = client.post(f"/api/actions/{action['id']}/tasks", json={"base_revision_id": revision["id"], "kind": "generate", "instruction": "frame_count=8; canvas=128x128。第12次挥剑，8帧攻击包含12个火花。"})
    assert response.status_code == 200, response.text
    spec = {**revision["spec"], "prompt": "角色持剑攻击。帧数: 12"}
    edited = save(client, action, revision, spec=spec).json()["revision"]
    rejected = client.post(f"/api/actions/{action['id']}/tasks", json={"base_revision_id": edited["id"], "kind": "generate"})
    assert rejected.status_code == 422
    assert rejected.json()["details"]["source"] == "prompt"
