import type { ProcessState, TechnologyStack } from "../studio-types";

export function RuntimeBulkControls({ states, busy, startingAction, onToggleAll }: { states: ProcessState[]; busy: boolean; startingAction: boolean; onToggleAll: (action: "start" | "stop") => Promise<void> }) {
  const runnable = states.filter((state) => state.command.length > 0);
  const starting = runnable.some((state) => state.phase === "starting");
  const allRunning = runnable.length > 0 && runnable.every((state) => state.running);
  const anyRunning = runnable.some((state) => state.running);
  return <section className="runtime-bulk-controls"><div><strong>서비스 전체 제어</strong><small>백엔드가 준비되면 프론트엔드를 시작합니다. 시작 실패 시 이번에 켠 프로세스만 되돌립니다.</small></div><button className="start-all" disabled={busy || starting || allRunning} onClick={() => void onToggleAll("start")}>{startingAction || starting ? "실행 준비 중" : "전체 실행"}</button><button className="stop-all" disabled={busy || starting || !anyRunning} onClick={() => void onToggleAll("stop")}>전체 중지</button></section>;
}

export function RuntimePreview({ frontend, device, onDevice }: { frontend?: ProcessState; device: "desktop" | "tablet" | "mobile"; onDevice: (device: "desktop" | "tablet" | "mobile") => void }) {
  const previewUrl = frontend?.phase === "ready" ? `http://localhost:${frontend.port}` : null;
  return <section className="preview-section"><div className="section-heading"><div><h2>서비스 미리보기</h2><p>{previewUrl ?? "프론트엔드를 시작하면 이곳에서 확인할 수 있습니다."}</p></div><div className="preview-actions">{(["desktop", "tablet", "mobile"] as const).map((item) => <button className={device === item ? "active" : ""} key={item} onClick={() => onDevice(item)}>{({ desktop: "PC", tablet: "태블릿", mobile: "모바일" } as const)[item]}</button>)}{previewUrl && <a href={previewUrl} target="_blank" rel="noreferrer">새 창</a>}</div></div>{previewUrl ? <div className={`preview-frame ${device}`}><iframe src={previewUrl} title="생성 서비스 미리보기" /></div> : <div className="preview-empty">프론트엔드가 중지되어 있습니다.</div>}</section>;
}

export function RuntimePortSettings({ backendPort, frontendPort, busy, saving, onBackendPort, onFrontendPort, onSave }: { backendPort: number; frontendPort: number; busy: boolean; saving: boolean; onBackendPort: (value: number) => void; onFrontendPort: (value: number) => void; onSave: () => Promise<void> }) {
  return <section className="port-settings"><div><strong>서비스 포트</strong><small>서비스를 중지한 상태에서 저장하세요. 이미 사용 중인 포트는 저장되지 않습니다.</small></div><label>백엔드<input disabled={busy} type="number" min="1024" max="65535" value={backendPort} onChange={(event) => onBackendPort(Number(event.target.value))} /></label><label>프론트엔드<input disabled={busy} type="number" min="1024" max="65535" value={frontendPort} onChange={(event) => onFrontendPort(Number(event.target.value))} /></label><button disabled={busy} onClick={() => void onSave()}>{saving ? "저장 중…" : "포트 저장"}</button></section>;
}

export function TechnologyStackPanel({ value }: { value: TechnologyStack }) {
  return <section className="technology-stack"><StackGroup title="백엔드" items={value.backend}/><StackGroup title="프론트엔드" items={value.frontend}/><StackGroup title="인프라" items={value.infrastructure}/></section>;
}

function StackGroup({ title, items }: { title: string; items: string[] }) {
  return <div><strong>{title}</strong><span>{items.map((item) => <i key={item}>{item}</i>)}</span></div>;
}
