"use client";

import { useEffect, useRef, useState } from "react";
import { apiRequest as request, isAbortError } from "../lib/api";
import type { EnvironmentSpec } from "../studio-types";

export function EnvironmentView({ projectId, onError }: { projectId: string; onError: (value: string) => void }) {
  const [values, setValues] = useState<Record<string, string>>({}); const [keyName, setKeyName] = useState(""); const [value, setValue] = useState(""); const [saved, setSaved] = useState(false);
  const [schema, setSchema] = useState<EnvironmentSpec[]>([]);
  const [busyAction, setBusyAction] = useState<"save" | "delete" | "">("");
  const valueInputRef = useRef<HTMLInputElement>(null);
  const busyRef = useRef(false);
  const mutationRef = useRef<AbortController | null>(null);
  const savedTimerRef = useRef<number | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void request<{ values: Record<string, string>; schema: EnvironmentSpec[] }>(`/projects/${projectId}/environment`, { signal: controller.signal })
      .then((data) => { setValues(data.values); setSchema(data.schema); })
      .catch((cause) => { if (!isAbortError(cause)) onError(String(cause)); });
    return () => {
      controller.abort();
      mutationRef.current?.abort();
      mutationRef.current = null;
      if (savedTimerRef.current !== null) window.clearTimeout(savedTimerRef.current);
      busyRef.current = false;
    };
  }, [projectId, onError]);
  async function runMutation(action: "save" | "delete", task: (signal: AbortSignal) => Promise<{ values: Record<string, string>; schema: EnvironmentSpec[] }>) {
    if (busyRef.current) return;
    busyRef.current = true;
    const controller = new AbortController();
    mutationRef.current = controller;
    setBusyAction(action);
    try {
      const data = await task(controller.signal);
      setValues(data.values); setSchema(data.schema); setKeyName(""); setValue("");
      if (action === "save") {
        setSaved(true);
        if (savedTimerRef.current !== null) window.clearTimeout(savedTimerRef.current);
        savedTimerRef.current = window.setTimeout(() => setSaved(false), 1600);
      }
    } catch (cause) { if (!isAbortError(cause)) onError(String(cause)); }
    finally {
      if (mutationRef.current === controller) {
        mutationRef.current = null; busyRef.current = false; setBusyAction("");
      }
    }
  }
  async function save() {
    if (!keyName || !value) return;
    await runMutation("save", (signal) => request<{ values: Record<string, string>; schema: EnvironmentSpec[] }>(`/projects/${projectId}/environment`, { method: "PUT", body: JSON.stringify({ values: { [keyName]: value } }), signal }));
  }
  async function remove() {
    if (!keyName || !(keyName in values)) return;
    await runMutation("delete", (signal) => request<{ values: Record<string, string>; schema: EnvironmentSpec[] }>(`/projects/${projectId}/environment/${encodeURIComponent(keyName)}`, { method: "DELETE", signal }));
  }
  const busy = Boolean(busyAction);
  return <div className="environment-page"><section aria-busy={busy}>
    <div className="section-heading"><div><h2>환경변수</h2><p>필수 여부와 공개 범위를 확인하고 값을 관리합니다. 항목을 누르면 수정할 수 있습니다.</p></div>{saved && <span className="saved">저장됨</span>}</div>
    <div className="env-list">{Object.entries(values).map(([key, item]) => { const spec = schema.find((entry) => entry.key === key); return <button disabled={busy} type="button" className={`env-row ${keyName === key ? "selected" : ""} ${spec?.required && !item ? "missing" : ""}`} key={key} onClick={() => { setKeyName(key); setValue(""); window.setTimeout(() => valueInputRef.current?.focus(), 0); }}><span><code>{key}</code><small>{spec?.description ?? "직접 추가한 환경변수"}</small></span><span>{item || "미설정"}<small>{spec && [spec.required ? "필수" : "선택", spec.secret ? "비밀값" : spec.client_exposed ? "프론트 공개" : "서버 전용", spec.format, spec.restart_required ? "재시작 필요" : "즉시 반영"].join(" · ")}</small></span></button>})}{Object.keys(values).length === 0 && <p className="env-empty">코드에서 사용하는 환경변수가 없습니다.</p>}</div>
    <div className="env-add"><label>변수 이름<input disabled={busy} value={keyName} onChange={(e) => setKeyName(e.target.value.toUpperCase())} placeholder="API_KEY" /></label><label>새 값<input disabled={busy} ref={valueInputRef} type="text" value={value} onChange={(e) => setValue(e.target.value)} placeholder={keyName && keyName in values ? "새 값으로 교체" : "값 입력"} /></label><button disabled={busy || !keyName || !value} onClick={() => void save()}>{busyAction === "save" ? "저장 중…" : keyName && keyName in values ? "수정" : "추가"}</button>{keyName && keyName in values && <button disabled={busy} className="danger" onClick={() => void remove()}>{busyAction === "delete" ? "삭제 중…" : "삭제"}</button>}</div>
    <div className="security-note"><span>⌁</span><p><strong>비밀값은 프론트 공개 변수로 저장할 수 없습니다.</strong><br />실제 값은 다시 표시되지 않으며 필수값이 없으면 서비스 실행을 차단합니다.</p></div>
  </section></div>;
}
