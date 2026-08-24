"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Message = { role: "user" | "assistant"; content: string };
type StoredMessage = { role: "system" | Message["role"]; content: string };
type Thread = { thread_id: string; title: string; updated_at: string };
type ThreadDocument = Thread & { messages: StoredMessage[] };

export default function ChatApp() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadThreads = useCallback(async () => {
    const response = await fetch("/api/backend/threads");
    if (response.ok) setThreads(await response.json());
  }, []);

  useEffect(() => { void loadThreads(); }, [loadThreads]);

  async function selectThread(threadId: string) {
    const response = await fetch(`/api/backend/threads/${encodeURIComponent(threadId)}`);
    if (!response.ok) return;
    const thread: ThreadDocument = await response.json();
    setActiveId(thread.thread_id);
    setMessages(thread.messages.filter((message): message is Message => message.role !== "system"));
    setError(null);
  }

  function startNew() {
    setActiveId(null);
    setMessages([]);
    setDraft("");
    setError(null);
  }

  async function removeThread(threadId: string, event: React.MouseEvent) {
    event.stopPropagation();
    await fetch(`/api/backend/threads/${encodeURIComponent(threadId)}`, { method: "DELETE" });
    if (activeId === threadId) startNew();
    await loadThreads();
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || sending) return;

    setSending(true);
    setError(null);
    setDraft("");
    setMessages((current) => [...current, { role: "user", content: message }]);
    try {
      const response = await fetch("/api/backend/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message, thread_id: activeId }),
      });
      if (!response.ok) throw new Error(await response.text());
      const result: { thread_id: string; reply: string } = await response.json();
      setActiveId(result.thread_id);
      setMessages((current) => [...current, { role: "assistant", content: result.reply }]);
      await loadThreads();
    } catch (caught) {
      setMessages((current) => current.slice(0, -1));
      setDraft(message);
      setError(caught instanceof Error ? caught.message : "응답을 받을 수 없습니다.");
    } finally {
      setSending(false);
    }
  }

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand"><span>✦</span><div><strong>gemma-mcp</strong><small>personal workspace</small></div></div>
        <button className="new" onClick={startNew}>+ 새 대화</button>
        <nav aria-label="대화 목록">
          {threads.map((thread) => <button key={thread.thread_id} className={`thread ${thread.thread_id === activeId ? "selected" : ""}`} onClick={() => void selectThread(thread.thread_id)}>
            <span>{thread.title}</span><i onClick={(event) => void removeThread(thread.thread_id, event)} aria-label="대화 삭제">×</i>
          </button>)}
        </nav>
        <p className="storage">대화 이력은 SeaweedFS S3에 저장됩니다.</p>
      </aside>
      <section className="chat">
        <header><div><strong>{activeId ? "대화" : "새 대화"}</strong><p>Gemma · FastAPI · FastMCP</p></div><span className="status">● 로컬</span></header>
        <div className="messages">
          {messages.length === 0 && <div className="empty"><h1>무엇을 도와드릴까요?</h1><p>개인용 Gemma 대화 공간입니다. MCP 도구와 RAG를 이 기반 위에 추가할 수 있습니다.</p></div>}
          {messages.map((message, index) => <article key={index} className={`message ${message.role}`}><div className="avatar">{message.role === "user" ? "나" : "✦"}</div><div className="content"><Markdown remarkPlugins={[remarkGfm]}>{message.content}</Markdown></div></article>)}
          {sending && <article className="message assistant"><div className="avatar">✦</div><div className="content waiting">생각하는 중…</div></article>}
        </div>
        <form onSubmit={send}>
          {error && <p className="error">{error}</p>}
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Gemma에게 메시지 보내기" rows={3} disabled={sending} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} />
          <div className="composer-footer"><small>Enter 전송 · Shift+Enter 줄바꿈</small><button type="submit" disabled={!draft.trim() || sending}>보내기</button></div>
        </form>
      </section>
    </main>
  );
}
