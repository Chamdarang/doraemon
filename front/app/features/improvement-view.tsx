"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import type { ImprovementPlan, Job, Message } from "../studio-types";
import { JobProgress } from "./studio-shared";

type ImprovementViewProps = {
  messages: Message[];
  plan: ImprovementPlan | null;
  thinking: boolean;
  jobs: Job[];
  onSend: (value: string) => Promise<void>;
  onApply: () => Promise<void>;
};

export function ImprovementView({ messages, plan, thinking, jobs, onSend, onApply }: ImprovementViewProps) {
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const latest = jobs[0];
  const canApply = Boolean(plan?.draft.changes.length && plan.draft.acceptance_criteria.length && !plan.draft.open_questions.length && !plan.applied_at);

  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [messages, thinking]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim() || thinking) return;
    const value = text.trim();
    setText("");
    await onSend(value);
  }

  return <div className="planning-grid"><section className="chat-panel"><div className="panel-title"><div><span className="spark">✦</span><strong>고도화 파트너</strong></div><small>현재 코드 기반</small></div><div className="messages">{messages.length === 0 && <div className="welcome-message"><span>↗</span><h2>어떤 점을 개선할까요?</h2><p>현재 구현을 분석한 뒤 필요한 파일만 수정합니다. 화면 디자인, 기능, 오류, 사용성 개선을 요청해보세요.</p></div>}{messages.map((message) => <article key={message.id} className={`message ${message.role}`}><span>{message.role === "assistant" ? "P" : "나"}</span><div>{message.content}</div></article>)}{thinking && <article className="message assistant"><span>P</span><div className="typing"><i /><i /><i /></div></article>}<div ref={end} /></div><form className="composer" onSubmit={submit}><textarea value={text} onChange={(event) => setText(event.target.value)} placeholder="예: 지금 화면을 실제 여행 서비스처럼 고도화해줘" rows={2} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} /><button disabled={!text.trim() || thinking}>↑</button><small>Enter 전송 · Shift+Enter 줄바꿈</small></form></section><aside className="plan-panel"><div className="panel-title"><div><strong>개선 변경안</strong></div><span className="stage-pill">파일 단위 적용</span></div>{!plan ? <div className="plan-empty"><span>↗</span><p>개선 요청을 보내면 분석과 변경 파일이 여기에 정리됩니다.</p></div> : <><section className="plan-section"><h3>{plan.draft.goal}</h3><p>{plan.draft.analysis}</p></section><section className="plan-section"><h3>변경 파일 <b>{plan.draft.changes.length}</b></h3>{plan.draft.changes.map((change) => <div className="decision" key={`${change.action}-${change.path}`}><small>{({ add: "추가", modify: "수정", delete: "삭제" } as const)[change.action]}</small><strong><code>{change.path}</code></strong><p>{change.reason}</p></div>)}</section>{plan.draft.open_questions.length > 0 && <section className="plan-section"><h3>확인할 내용 <b>{plan.draft.open_questions.length}</b></h3><ul className="questions">{plan.draft.open_questions.map((item) => <li key={item}>{item}</li>)}</ul></section>}{plan.draft.acceptance_criteria.length > 0 && <section className="plan-section"><h3>완료 기준</h3><ul className="questions">{plan.draft.acceptance_criteria.map((item) => <li key={item}>{item}</li>)}</ul></section>}</>}<div className="generate-zone">{latest && !["completed", "failed", "cancelled"].includes(latest.status) ? <JobProgress job={latest} /> : <><button className="generate-button" disabled={!canApply || thinking} onClick={() => void onApply()}><span>↗</span>변경사항 승인하고 적용</button><small>{canApply ? "추가 LLM 대화 없이 바로 승인·적용할 수 있습니다." : "남은 확인 사항을 결정하면 적용할 수 있습니다."}</small></>}</div></aside></div>;
}
