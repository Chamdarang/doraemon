import type { ProcessState, UsageRecord, VersionDiff } from "../studio-types";

export function ProcessCard({ state, logs, busy, onToggle, onOpenRepair }: {
  state: ProcessState;
  logs?: string;
  busy: boolean;
  onToggle: (target: "backend" | "frontend", running: boolean) => Promise<void>;
  onOpenRepair: (draft: string) => void;
}) {
  const runnable = state.command.length > 0;
  const label = state.phase === "starting" ? "시작 준비 중…" : state.phase === "ready" ? `준비 완료 · PID ${state.pid}` : state.phase === "error" ? "시작 실패" : "중지됨";
  const repairDraft = [
    `${state.target === "backend" ? "백엔드" : "프론트엔드"} 실행 실패를 수정해주세요.`,
    `실행 명령: ${(state.command ?? []).join(" ") || "명령 정보 없음"}`,
    `포트: ${state.port}`,
    `오류: ${state.message || "상태 메시지 없음"}`,
    `최근 로그:\n${(logs || "로그 없음").slice(-6000)}`,
  ].join("\n\n");
  return <article className={`runtime-card service-runtime phase-${state.phase}`}>
    <div className="runtime-card-head">
      <div><span className={`runtime-icon ${state.target}`}>{state.target === "backend" ? "BE" : "FE"}</span><div><h3>{state.target === "backend" ? "백엔드" : "프론트엔드"}</h3><p>{runnable ? `localhost:${state.port}` : "실행 명령 미탐지"}</p></div></div>
      <span className={`runtime-status ${state.phase === "ready" ? "running" : state.phase}`}>{runnable ? label : "실행 대상 아님"}</span>
      <div className="runtime-actions">{state.phase === "error" && <button disabled={busy} className="repair" onClick={() => onOpenRepair(repairDraft)}>이 로그로 오류 수정</button>}<button disabled={busy || !runnable || state.phase === "starting"} className={state.running ? "stop" : "start"} onClick={() => void onToggle(state.target, state.running)}>{!runnable ? "명령 없음" : state.phase === "starting" ? "준비 중" : state.running ? "중지" : "시작"}</button></div>
    </div>
    {state.message && <p className={`runtime-message ${state.phase}`}>{state.message}</p>}
    <div className="attached-log"><strong>{state.target === "backend" ? "백엔드" : "프론트엔드"} 실시간 로그</strong><small>2초마다 상태와 함께 갱신</small><pre>{logs || "표시할 로그가 없습니다."}</pre></div>
  </article>;
}

export function VersionDiffPanel({ value }: { value: VersionDiff }) {
  const labels = { added: "추가", modified: "수정", deleted: "삭제" } as const;
  return <section className="version-diff-panel"><div className="version-diff-summary"><span className="added">추가 {value.added}</span><span className="modified">수정 {value.modified}</span><span className="deleted">삭제 {value.deleted}</span><span>동일 {value.unchanged}</span>{value.runtime_changed && <span className="runtime-changed">실행 설정 변경</span>}</div>{value.files.length ? <div className="version-diff-files">{value.files.map((file) => <details key={file.path}><summary><i className={file.status}>{labels[file.status]}</i><code>{file.path}</code><span>+{file.additions} / -{file.deletions}</span></summary><pre>{file.binary ? "바이너리 또는 큰 파일이 변경되었습니다." : file.diff || "내용 차이를 표시할 수 없습니다."}{file.truncated && !file.binary ? "\n\n… 변경 내용이 길어 일부만 표시합니다." : ""}</pre></details>)}</div> : <p>현재 파일과 차이가 없습니다.</p>}{value.truncated_files > 0 && <small>변경 파일 {value.truncated_files}개는 목록에서 생략했습니다.</small>}</section>;
}

export function UsageRecordRow({ value }: { value: UsageRecord }) {
  const labels = { planning: "기획", improvement_planning: "개선 기획", generation: "최초 생성", improvement_generation: "개선 생성", repair: "오류 수정" } as const;
  const uncached = Math.max(0, value.input_tokens - value.cached_input_tokens);
  return <article className="usage-record"><div><strong>{labels[value.kind]}</strong><code>{value.provider} · {value.model}</code><small>{new Date(value.created_at).toLocaleString("ko-KR")}</small></div><dl><span><dt>일반 입력</dt><dd>{uncached.toLocaleString()}</dd></span><span><dt>캐시 입력</dt><dd>{value.cached_input_tokens.toLocaleString()}</dd></span><span><dt>출력</dt><dd>{value.output_tokens.toLocaleString()}</dd></span><span><dt>전체</dt><dd>{value.total_tokens.toLocaleString()}</dd></span></dl></article>;
}
