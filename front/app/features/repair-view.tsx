"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

type Message = { id: string; role: "user" | "assistant"; content: string; created_at: string };
type Job = { id: string; status: string; message: string; error: string | null; updated_at: string };

export function RepairView({ initialText = "", messages, jobs, busy, onRepair, onCancel }: {
  initialText?: string;
  messages: Message[];
  jobs: Job[];
  busy: boolean;
  onRepair: (content: string) => Promise<void>;
  onCancel: (jobId: string) => Promise<void>;
}) {
  const [text, setText] = useState(initialText);
  const end = useRef<HTMLDivElement>(null);
  const active = jobs.find((job) => !["completed", "failed", "cancelled"].includes(job.status));
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [messages, active]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim() || busy || active) return;
    const content = text.trim(); setText(""); await onRepair(content);
  }
  return <div className="repair-page"><section className="chat-panel"><div className="panel-title"><div><span className="spark">✦</span><strong>오류 수정</strong></div><small>로그 · 소스 기반</small></div>{initialText && <div className="repair-cost-note"><strong>실행 정보와 최근 로그를 가져왔습니다.</strong><span>아직 LLM 요청은 보내지 않았습니다. 내용을 확인한 뒤 전송할 때만 오류 수정 비용이 발생합니다.</span></div>}<div className="messages">{messages.length === 0 && <div className="welcome-message"><span>⌁</span><h2>작동하지 않는 부분을 알려주세요</h2><p>최근 실행 로그와 현재 소스를 분석하고, 변경 전 체크포인트를 만든 뒤 필요한 파일만 수정합니다.</p></div>}{messages.map((message) => <article key={message.id} className={`message ${message.role}`}><span>{message.role === "assistant" ? "P" : "나"}</span><div>{message.content}</div></article>)}{active && <article className="message assistant"><span>P</span><div><strong>{active.message}</strong>{active.error && <p>{active.error}</p>}<button className="inline-danger" onClick={() => void onCancel(active.id)}>작업 취소</button></div></article>}<div ref={end} /></div><form className="composer" onSubmit={submit}><textarea value={text} onChange={(event) => setText(event.target.value)} placeholder="예: 프론트 시작 시 빈 화면이 나오고 콘솔에 모듈 오류가 표시돼" rows={2} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} /><button aria-label="오류 수정 시작" title="내용을 확인하고 오류 수정 시작" disabled={!text.trim() || busy || Boolean(active)}>↑</button><small>Enter 또는 전송 버튼을 누를 때만 LLM 오류 수정 요청이 시작됩니다. Shift+Enter는 줄바꿈입니다.</small></form></section></div>;
}
