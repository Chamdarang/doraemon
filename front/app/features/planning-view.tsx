"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import type { Job, Message, Plan } from "../studio-types";
import { compactChatMessage, JobProgress, StagePill } from "./studio-shared";

type PlanningViewProps = {
  messages: Message[];
  plan: Plan | null;
  thinking: boolean;
  jobs: Job[];
  onSend: (value: string, applyRecommendations?: boolean) => Promise<void>;
  onGenerate: () => Promise<void>;
  onOpenRepair: () => void;
  onSaveSpecification: (service: string, technical: string) => Promise<void>;
};

const requiredTechnicalDecisions = ["architecture", "components", "frontend_stack", "backend_stack", "persistence", "repository_layout", "runtime_infrastructure", "testing"];

export function PlanningView({ messages, plan, thinking, jobs, onSend, onGenerate, onOpenRepair, onSaveSpecification }: PlanningViewProps) {
  const [text, setText] = useState("");
  const latestJob = jobs[0];
  const confirmedDecisions = new Set(plan?.draft.decisions.filter((item) => item.confirmed).map((item) => item.category.toLowerCase()) ?? []);
  const technicalReady = requiredTechnicalDecisions.every((category) => confirmedDecisions.has(category));
  const canApprove = Boolean(plan?.approved || (technicalReady && plan?.draft.implementation_plan && plan.draft.service_specification && plan.draft.technical_specification));
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ block: "end", behavior: "smooth" }); }, [messages, thinking]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim() || thinking) return;
    const value = text.trim();
    setText("");
    await onSend(value);
  }

  return (
    <div className="planning-grid">
      <section className="chat-panel">
        <div className="panel-title"><div><span className="spark">✦</span><strong>기획 파트너</strong></div><small>설정된 LLM</small></div>
        <div className="messages">
          {messages.length === 0 && <div className="welcome-message"><span>✦</span><h2>아이디어를 구체화해볼까요?</h2><p>만들고 싶은 서비스를 자유롭게 설명해주세요. 필요한 기능과 기술은 대화를 통해 함께 결정합니다.</p></div>}
          {messages.map((message) => <article key={message.id} className={`message ${message.role}`}><span>{message.role === "assistant" ? "P" : "나"}</span><div>{compactChatMessage(message)}</div></article>)}
          {thinking && <article className="message assistant"><span>P</span><div className="typing"><i /><i /><i /></div></article>}
          <div ref={messagesEndRef} className="messages-end" />
        </div>
        <form className="composer" onSubmit={submit}><textarea value={text} onChange={(event) => setText(event.target.value)} placeholder="답변하거나 새로운 요구사항을 입력하세요" rows={2} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} /><button disabled={!text.trim() || thinking}>↑</button><small>Enter 전송 · Shift+Enter 줄바꿈</small></form>
      </section>
      <aside className="plan-panel">
        <div className="panel-title"><div><strong>서비스 명세</strong></div><StagePill stage={plan?.draft.stage} /></div>
        {!plan ? <div className="plan-empty"><span>◎</span><p>대화를 시작하면 결정된 내용이 여기에 정리됩니다.</p></div> : <>
          <section className="plan-section"><h3>결정된 내용 <b>{plan.draft.decisions.length}</b></h3>{plan.draft.decisions.map((item, index) => <div className="decision" key={`${item.category}-${index}`}><small>{item.category}</small><strong>{item.choice}</strong><p>{item.rationale}</p></div>)}</section>
          {plan.draft.open_questions.length > 0 && <section className="plan-section"><h3>남은 질문 <b>{plan.draft.open_questions.length}</b></h3><ul className="questions">{plan.draft.open_questions.map((question) => <li key={question}>{question}</li>)}</ul></section>}
          {plan.draft.implementation_plan && <section className="plan-section structure-plan"><h3>{technicalReady ? "확정된 프로젝트 구조" : "검토 중인 프로젝트 구조"}</h3><div className="architecture-summary"><small>{technicalReady ? "확정 아키텍처" : "제안 아키텍처"}</small><p>{plan.draft.implementation_plan.architecture}</p></div><div className="component-chips">{plan.draft.implementation_plan.components.map((component) => <span key={component}>{component}</span>)}</div><div className="directory-plan">{plan.draft.implementation_plan.directories.map((item) => <div key={item.path}><code>{item.path}</code><small>{item.purpose}</small></div>)}</div><details><summary>데이터 · API · 실행 · 테스트</summary><dl><dt>데이터와 상태</dt><dd>{plan.draft.implementation_plan.data_and_state}</dd><dt>API와 연동</dt><dd>{plan.draft.implementation_plan.api_and_integrations}</dd><dt>실행과 설정</dt><dd>{plan.draft.implementation_plan.runtime_and_configuration}</dd><dt>테스트</dt><dd>{plan.draft.implementation_plan.testing_strategy}</dd></dl></details></section>}
          {plan.draft.specification && <SpecificationEditor key={plan.updated_at} plan={plan} onSave={onSaveSpecification} />}
        </>}
        <div className="generate-zone">
          {latestJob?.status === "failed" && plan?.approved ? <><button className="generate-button" onClick={onOpenRepair}><span>↗</span>현재 파일 오류 수정</button><button className="secondary-generate" disabled={thinking} onClick={() => void onGenerate()}>저장된 생성 결과 다시 적용</button><small>유료 LLM 호출 없이 저장된 생성 결과의 파일 적용을 다시 시도합니다.</small></> : latestJob && !["completed", "failed", "cancelled"].includes(latestJob.status) ? <JobProgress job={latestJob} /> : <>
            <button className="generate-button" disabled={!canApprove || thinking} onClick={() => void onGenerate()}><span>✦</span>{plan?.approved ? "다시 생성하기" : "현재 명세 승인하고 생성"}</button>
            <small>{canApprove ? "확정한 서비스·아키텍처·기술 스택을 기준으로 생성합니다." : "아키텍처와 프론트·백엔드 기술 스택까지 함께 확정하면 승인할 수 있습니다."}</small>
          </>}
        </div>
      </aside>
    </div>
  );
}

function SpecificationEditor({ plan, onSave }: { plan: Plan; onSave: (service: string, technical: string) => Promise<void> }) {
  const [service, setService] = useState(plan.draft.service_specification ?? plan.draft.specification ?? "");
  const [technical, setTechnical] = useState(plan.draft.technical_specification ?? JSON.stringify(plan.draft.implementation_plan, null, 2));
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  async function save() {
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    try { await onSave(service, technical); }
    finally { savingRef.current = false; setSaving(false); }
  }
  return <details className="specification-editor"><summary>서비스·기술 명세 직접 편집</summary><label>서비스 명세<textarea value={service} onChange={(event) => setService(event.target.value)} rows={10} /></label><label>기술 명세<textarea value={technical} onChange={(event) => setTechnical(event.target.value)} rows={12} /></label><button disabled={saving || service.trim().length < 20 || technical.trim().length < 20} onClick={() => void save()}>{saving ? "저장 중…" : "LLM 호출 없이 저장"}</button><small>저장하면 기존 승인은 해제되며 다시 검토 후 생성할 수 있습니다.</small></details>;
}
