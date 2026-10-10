from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, Field, ConfigDict, model_validator


def uid():
    return uuid4().hex


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Rect(Model):
    x: int = 0
    y: int = 0
    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)


class Canvas(Model):
    width: int = Field(default=256, gt=0, le=2048)
    height: int = Field(default=256, gt=0, le=2048)
    pivot_x: int = 128
    pivot_y: int = 224
    ground_y: int = 224

    @model_validator(mode='after')
    def bounds(self):
        if not 0 <= self.pivot_x <= self.width or not 0 <= self.pivot_y <= self.height:
            raise ValueError('pivot 必须位于画布边界内')
        return self


class Body(Model):
    width: int = Field(default=40, gt=0, le=2048)
    height: int = Field(default=100, gt=0, le=2048)
    reference_rect: Rect | None = None


class Frame(Model):
    id: str = Field(default_factory=uid)
    duration_ms: int = Field(default=100, ge=1, le=60000)
    status: Literal['pending', 'passed', 'problem'] = 'pending'
    events: list[str] = Field(default_factory=list)
    points: dict[str, list[int]] = Field(default_factory=dict)

    @model_validator(mode='after')
    def point_shape(self):
        if any(len(p) != 2 for p in self.points.values()):
            raise ValueError('参考点必须包含两个坐标')
        return self


class Transform(Model):
    dx: int = 0
    dy: int = 0
    anchor_x: float | None = None
    anchor_y: float | None = None
    scale: float = Field(default=1, gt=0, le=64)
    rotation: float = 0
    flip_x: bool = False
    flip_y: bool = False
    opacity: float = Field(default=1, ge=0, le=1)


class Exposure(Model):
    id: str = Field(default_factory=uid)
    asset_id: str
    duration_ms: int = Field(default=100, ge=1, le=60000)
    transform: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def transform_valid(self):
        Transform.model_validate(self.transform)
        return self


class Track(Model):
    id: str = Field(default_factory=uid)
    name: str = '角色'
    kind: Literal['character', 'effect', 'reference'] = 'character'
    visible: bool = True
    locked: bool = False
    export: bool = True
    start_ms: int = Field(default=0, ge=0, le=3600000)
    end_behavior: Literal['hide', 'hold', 'loop'] = 'hide'
    transform: Transform = Field(default_factory=Transform)
    exposures: list[Exposure] = Field(default_factory=list, max_length=1000)

    @model_validator(mode='after')
    def exposure_ids(self):
        if len({e.id for e in self.exposures}) != len(self.exposures):
            raise ValueError('曝光 ID 重复')
        return self


class Issue(Model):
    id: str = Field(default_factory=uid)
    frame_id: str
    track_id: str | None = None
    rect: Rect | None = None
    tag: str = '衔接'
    note: str = ''
    status: Literal['open', 'resolved', 'recheck'] = 'open'
    author: str = 'user'
    original_label: str = ''


class Prompt(Model):
    identity: str = ''
    motion: str = ''
    frame_notes: str = ''
    changes: str = ''
    reference_ids: list[str] = Field(default_factory=list)
    final_text: str = ''


class State(Model):
    canvas: Canvas = Field(default_factory=Canvas)
    body: Body = Field(default_factory=Body)
    frames: list[Frame] = Field(default_factory=list, max_length=500)
    tracks: list[Track] = Field(default_factory=list, max_length=32)
    issues: list[Issue] = Field(default_factory=list, max_length=2000)
    prompt: Prompt = Field(default_factory=Prompt)
    status: Literal['draft', 'candidate', 'accepted'] = 'draft'

    @model_validator(mode='after')
    def refs(self):
        for objects in [self.frames, self.tracks, self.issues]:
            if len({x.id for x in objects}) != len(objects):
                raise ValueError('对象 ID 重复')
        fids, tids = {f.id for f in self.frames}, {t.id for t in self.tracks}
        for issue in self.issues:
            if issue.frame_id not in fids or (issue.track_id and issue.track_id not in tids):
                raise ValueError('问题引用了不存在的帧或图层')
        if sum(f.duration_ms for f in self.frames) > 3600000:
            raise ValueError('动作不能超过一小时')
        return self


class VersionWrite(Model):
    expected_revision: int
    state: State
    name: str | None = None


class Revision(Model):
    expected_revision: int
