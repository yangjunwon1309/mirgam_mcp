from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class Message(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(min_length=1, max_length=100_000)
    created_at: datetime
    trace: list[dict[str, object]] | None = None


class Thread(BaseModel):
    thread_id: str
    title: str
    updated_at: datetime


class ThreadDocument(BaseModel):
    thread_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[Message] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=100_000)
    thread_id: str | None = None


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=255)
    password: SecretStr = Field(min_length=1, max_length=1024)


class AuthenticatedUser(BaseModel):
    account_id: int
    farm_name: str
    username: str | None = None


class ChatResponse(BaseModel):
    thread_id: str
    reply: str


class BeaconLocation(BaseModel):
    model_config = ConfigDict(extra="allow")
    site: str | None = Field(None, max_length=120)
    zone: str | None = Field(None, max_length=120)
    row: str | None = Field(None, max_length=80)
    position: str | None = Field(None, max_length=120)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)


class BeaconMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: int = 1
    label: str = Field(min_length=1, max_length=64)
    location: BeaconLocation = Field(default_factory=BeaconLocation)
    installed_at: str | None = Field(None, max_length=32)
    hardware: dict[str, object] = Field(default_factory=dict)
    sensors: list[dict[str, object]] = Field(default_factory=list, max_length=32)
    tags: list[str] = Field(default_factory=list, max_length=24)
    custom: dict[str, object] = Field(default_factory=dict)


class BeaconConfigureRequest(BaseModel):
    farm_id: str = Field(min_length=1, max_length=64)
    metadata: BeaconMetadata
    interval_s: int = Field(300, ge=60, le=14400)
    requested_data: list[Literal["sensor", "image"]] = Field(default_factory=lambda: ["sensor"], max_length=2)
    attach: bool = True

    @field_validator("requested_data")
    @classmethod
    def unique_data_types(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class BeaconIntervalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interval_s: int = Field(ge=60, le=14400)


class BeaconActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minutes: int | None = Field(None, ge=1, le=30)
    hold_s: int | None = Field(None, ge=0, le=180)


class BeaconCommandRequest(BaseModel):
    type: Literal["sensor", "image"]
    fs: Literal["QVGA", "VGA", "SVGA", "XGA", "HD", "SXGA", "UXGA"] = "VGA"
    q: int = Field(12, ge=4, le=40)
    warm: int = Field(500, ge=0, le=3000)


class BeaconDataDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["sensor", "image", "checkin", "command"]
    ids: list[str] | None = Field(None, min_length=1, max_length=1000)
    sensor_ids: list[str] | None = Field(None, min_length=1, max_length=32)
    before: datetime | None = None
    all: bool = False
    confirm_label: str | None = Field(None, max_length=64)
    dry_run: bool = False

    @model_validator(mode="after")
    def one_mode(self) -> "BeaconDataDeleteRequest":
        modes = [self.ids is not None, self.before is not None, self.all]
        if sum(modes) != 1:
            raise ValueError("ids, before, all 중 정확히 하나를 지정하세요.")
        if self.sensor_ids is not None and (self.kind != "sensor" or self.ids is not None):
            raise ValueError("sensor_ids는 kind=sensor의 기간·전체 삭제에서만 쓸 수 있습니다.")
        if self.before is not None and self.before.tzinfo is None:
            raise ValueError("before에는 시간대가 있어야 합니다.")
        return self

    @property
    def mode(self) -> str:
        return "ids" if self.ids is not None else "all" if self.all else "before"
