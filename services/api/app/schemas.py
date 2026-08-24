from datetime import datetime

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(min_length=1, max_length=100_000)
    created_at: datetime


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


class ChatResponse(BaseModel):
    thread_id: str
    reply: str
