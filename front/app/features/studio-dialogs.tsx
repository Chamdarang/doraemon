"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import type { TrashItem } from "../studio-types";

function useDialogBehavior(onClose: () => void, disabled = false) {
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !disabled) onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.body.style.overflow = previousOverflow;
    };
  }, [disabled, onClose]);
}

export function CreateServiceDialog({ onClose, onCreate }: { onClose: () => void; onCreate: (name: string, description: string) => Promise<void> }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [submitError, setSubmitError] = useState("");
  const valid = name.trim() && description.trim().length >= 10;
  useDialogBehavior(onClose, busy);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setSubmitError("");
    try { await onCreate(name.trim(), description.trim()); }
    catch (cause) { setSubmitError(cause instanceof Error ? cause.message : "서비스를 만들지 못했습니다."); }
    finally { busyRef.current = false; setBusy(false); }
  }

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="create-service-title" onSubmit={submit}>
      <button type="button" className="dialog-close" aria-label="새 서비스 창 닫기" disabled={busy} onClick={onClose}>×</button>
      <div className="dialog-icon">✦</div><h2 id="create-service-title">새 서비스 시작</h2>
      <p>지금은 거친 아이디어여도 괜찮아요. Doraemon이 질문하며 구체화합니다.</p>
      {submitError && <div className="dialog-error"><span>!</span><p>{submitError}</p></div>}
      <label>서비스 이름<input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="예: 동네 맛집 기록" maxLength={80} /></label>
      <label>만들고 싶은 서비스<textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="누가, 어떤 상황에서, 무엇을 할 수 있는 서비스인지 자유롭게 적어주세요." rows={5} maxLength={10000} /></label>
      <button className="dialog-submit" disabled={!valid || busy}>{busy ? "연결하는 중…" : submitError ? "다시 시도" : "기획 시작하기"}</button>
    </form>
  </div>;
}

export function ImportServiceDialog({ onClose, onImport }: { onClose: () => void; onImport: (name: string, description: string, file: File) => Promise<void> }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("기존 ZIP 프로젝트를 Doraemon 서비스로 가져옵니다");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [submitError, setSubmitError] = useState("");
  useDialogBehavior(onClose, busy);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || !name.trim() || description.trim().length < 10 || busyRef.current) return;
    busyRef.current = true;
    setBusy(true); setSubmitError("");
    try { await onImport(name.trim(), description.trim(), file); onClose(); }
    catch (cause) { setSubmitError(cause instanceof Error ? cause.message : "ZIP 프로젝트를 가져오지 못했습니다"); }
    finally { busyRef.current = false; setBusy(false); }
  }

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <form className="dialog import-dialog" role="dialog" aria-modal="true" aria-labelledby="import-service-title" onSubmit={submit}>
      <button type="button" className="dialog-close" aria-label="가져오기 창 닫기" disabled={busy} onClick={onClose}>×</button>
      <div className="dialog-icon">⇧</div><h2 id="import-service-title">서비스 가져오기</h2>
      <p>백엔드·프론트엔드 구조와 실행 명령을 ZIP에서 탐지합니다. .env 값과 의존성·빌드 폴더는 제외됩니다.</p>
      {submitError && <div className="dialog-error"><span>!</span><p>{submitError}</p></div>}
      <label>ZIP 파일<input type="file" accept=".zip,application/zip" onChange={(event) => { const next = event.target.files?.[0] ?? null; setFile(next); if (next && !name) setName(next.name.replace(/\.zip$/i, "")); }} /></label>
      <label>서비스 이름<input value={name} onChange={(event) => setName(event.target.value)} maxLength={80} /></label>
      <label>서비스 설명<textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} maxLength={10000} /></label>
      <small>ZIP 100MB · 압축 해제 500MB · 최대 5,000개 파일</small>
      <button className="dialog-submit" disabled={!file || !name.trim() || description.trim().length < 10 || busy}>{busy ? "가져오는 중…" : "가져오기"}</button>
    </form>
  </div>;
}

export function TrashDialog({ items, busyAction = "", onClose, onRestore, onDelete }: { items: TrashItem[]; busyAction?: string; onClose: () => void; onRestore: (item: TrashItem) => void; onDelete: (item: TrashItem) => void }) {
  const busy = Boolean(busyAction);
  useDialogBehavior(onClose, busy);
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <section className="dialog trash-dialog" role="dialog" aria-modal="true" aria-labelledby="trash-title" aria-busy={busy}>
      <button className="dialog-close" aria-label="휴지통 창 닫기" disabled={busy} onClick={onClose}>×</button>
      <div className="dialog-icon">♲</div><h2 id="trash-title">휴지통</h2>
      <p>복구하면 원래 서비스 목록으로 돌아옵니다. 영구 삭제한 항목은 되돌릴 수 없습니다.</p>
      <div className="trash-list">{items.length ? items.map((item) => <article key={item.id}><div><strong>{item.name}</strong><small>{item.description}</small><time>{new Date(item.deleted_at).toLocaleString("ko-KR")}</time></div><button disabled={busy} onClick={() => onRestore(item)}>{busyAction === `restore-${item.id}` ? "복구 중…" : "복구"}</button><button disabled={busy} className="permanent" onClick={() => onDelete(item)}>{busyAction === `delete-${item.id}` ? "삭제 중…" : "영구 삭제"}</button></article>) : <p>휴지통이 비어 있습니다.</p>}</div>
    </section>
  </div>;
}
