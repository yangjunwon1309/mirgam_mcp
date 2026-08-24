"""FastAPI entry point: chat API backed by SeaweedFS S3 JSON documents."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .schemas import ChatRequest, ChatResponse, Message, Thread, ThreadDocument
from .services.gemma import GemmaClient
from .services.thread_store import ThreadStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    store = ThreadStore(settings)
    store.ensure_bucket()
    app.state.thread_store = store
    app.state.gemma = GemmaClient(settings)
    yield


app = FastAPI(title="gemma-mcp-api", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def store(request: Request) -> ThreadStore:
    return request.app.state.thread_store


@app.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "model": settings.gemma_model, "mcp_url": settings.mcp_url}


@app.get("/threads", response_model=list[Thread])
async def list_threads(request: Request) -> list[Thread]:
    return store(request).list()


@app.get("/threads/{thread_id}", response_model=ThreadDocument)
async def get_thread(thread_id: str, request: Request) -> ThreadDocument:
    try:
        return store(request).load(thread_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Thread not found") from exc


@app.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(thread_id: str, request: Request) -> None:
    store(request).delete(thread_id)


@app.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    thread_store = store(request)
    if payload.thread_id:
        try:
            document = thread_store.load(payload.thread_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Thread not found") from exc
    else:
        document = thread_store.create(payload.message)

    document.messages.append(Message(role="user", content=payload.message, created_at=datetime.now(UTC)))
    reply = await request.app.state.gemma.reply(document.messages)
    document.messages.append(Message(role="assistant", content=reply, created_at=datetime.now(UTC)))
    thread_store.save(document)
    return ChatResponse(thread_id=document.thread_id, reply=reply)

