from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Spec(Model):
    canvas_width: int = Field(128, ge=1, le=1024)
    canvas_height: int = Field(128, ge=1, le=1024)
    pivot_x: int = 64
    pivot_y: int = 112
    body_width: int = Field(32, ge=1, le=4096)
    body_height: int = Field(64, ge=1, le=4096)
    target_frame_count: int = Field(8, ge=1, le=256)
    default_duration_ms: int = Field(100, ge=1, le=60000)
    motion_description: str = ""
    prompt: str = ""
    locked_notes: str = ""
    reference_ids: list[str] = Field(default_factory=list)
    loop: bool = True

    @model_validator(mode="after")
    def valid_pivot(self):
        if not (0 <= self.pivot_x <= self.canvas_width and 0 <= self.pivot_y <= self.canvas_height):
            raise ValueError("pivot 必须位于画布范围内")
        if self.target_frame_count * self.default_duration_ms > 120000:
            raise ValueError("规格默认总时长不可超过 120000ms")
        return self


class Frame(Model):
    id: str = Field(min_length=1, max_length=200)
    image_id: str
    duration_ms: int = Field(100, ge=1, le=60000)
    offset_x: int = Field(0, ge=-8192, le=8192)
    offset_y: int = Field(0, ge=-8192, le=8192)


class Effect(Model):
    id: str = Field(min_length=1, max_length=200)
    name: str = "特效"
    image_ids: list[str] = Field(default_factory=list, max_length=256)
    durations_ms: list[int] = Field(default_factory=list, max_length=256)
    start_ms: int = Field(0, ge=0, le=120000)
    x: int = Field(0, ge=-8192, le=8192)
    y: int = Field(0, ge=-8192, le=8192)
    opacity: float = Field(1, ge=0, le=1)
    z: Literal["back", "front"] = "front"
    visible: bool = True

    @model_validator(mode="after")
    def valid_durations(self):
        if len(self.image_ids) != len(self.durations_ms):
            raise ValueError("特效图片与时长数量必须相同")
        if any(t < 1 or t > 60000 for t in self.durations_ms) or sum(self.durations_ms) > 120000:
            raise ValueError("特效时长超出范围")
        return self


class Event(Model):
    id: str = Field(min_length=1)
    name: str
    frame_id: str
    offset_ms: int = Field(0, ge=0, le=60000)


class Rect(Model):
    x: int = Field(ge=0, le=4096)
    y: int = Field(ge=0, le=4096)
    width: int = Field(ge=1, le=4096)
    height: int = Field(ge=1, le=4096)


class Reference(Model):
    image_id: str
    purpose: Literal["identity", "style", "pose", "weapon"]
    note: str = ""


class ProjectCreate(Model):
    name: str = Field(min_length=1, max_length=200)


class AssetCreate(ProjectCreate):
    description: str = ""
    references: list[Reference] = Field(default_factory=list)


class AssetPatch(Model):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    references: list[Reference] | None = None


class ActionCreate(ProjectCreate):
    kind: Literal["idle", "attack", "custom"] = "custom"
    spec: Spec = Field(default_factory=Spec)


class ImageCreate(Model):
    filename: str = Field("image.png", max_length=300)
    data_base64: str = Field(max_length=28000000)
    source: Literal["upload", "edit"] = "upload"


class RevisionCreate(Model):
    base_revision_id: str
    label: str = "保存修订"
    author: Literal["human", "agent"] = "human"
    mode: Literal["working", "candidate"] = "working"
    spec: Spec | None = None
    frames: list[Frame] | None = Field(None, max_length=256)
    effects: list[Effect] | None = Field(None, max_length=32)
    events: list[Event] | None = Field(None, max_length=1024)


class Adopt(Model):
    revision_id: str
    expected_current_revision_id: str


class Review(Model):
    status: Literal["accepted", "needs_work"]


class Scale(Model):
    base_revision_id: str
    scale: float = Field(gt=0, le=16)
    canvas_width: int = Field(ge=1, le=1024)
    canvas_height: int = Field(ge=1, le=1024)
    label: str = "统一像素缩放"


class IssueCreate(Model):
    revision_id: str
    frame_id: str
    layer_id: str = "character"
    rect: Rect | None = None
    category: str
    message: str = Field(min_length=1)


class IssuePatch(Model):
    status: Literal["open", "needs_review", "resolved"] | None = None
    message: str | None = Field(None, min_length=1)


class TaskCreate(Model):
    base_revision_id: str
    kind: Literal["generate", "repair"]
    instruction: str = ""
    allowed_frame_ids: list[str] = Field(default_factory=list)
    allowed_rect: Rect | None = None


class TaskPatch(Model):
    status: Literal["running", "cancelled", "failed"]


class TaskResult(Model):
    base_revision_id: str
    label: str = "Agent 提交候选"
    frames: list[Frame] = Field(max_length=256)
    effects: list[Effect] | None = Field(None, max_length=32)
    events: list[Event] | None = Field(None, max_length=1024)
    submission_id: str | None = Field(None, max_length=200)
