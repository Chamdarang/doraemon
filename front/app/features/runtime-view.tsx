"use client";

import { Dispatch, SetStateAction, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, apiRequest as request, isAbortError } from "../lib/api";
import { useVisibilityPolling } from "../hooks/use-visibility-polling";
import type { InfrastructureOverview, InfrastructureServiceState, Job, LogChunk, MaintenanceSummary, ProcessState, ProjectOverview, RuntimeSnapshot, TechnologyStack, UsageRecord, UsageSummary, VersionDiff, VersionRecord } from "../studio-types";
import { formatBytes } from "./studio-shared";
import { InfrastructureStatusPanel } from "./infrastructure-status-panel";
import { GenerationCoverage } from "./generation-coverage";
import { RuntimeBulkControls, RuntimePortSettings, RuntimePreview, TechnologyStackPanel } from "./runtime-service-panels";
import { ProcessCard, UsageRecordRow, VersionDiffPanel } from "./runtime-widgets";

type CostMode = "economy" | "balanced" | "quality";
type JobFilter = "all" | Job["kind"] | "failed";

type RuntimeViewProps = {
  projectId: string;
  states: ProcessState[];
  jobs: Job[];
  usage: UsageSummary | null;
  versions: VersionRecord[];
  overview: ProjectOverview | null;
  costMode: CostMode;
  busyAction?: string | null;
  onStates: Dispatch<SetStateAction<ProcessState[]>>;
  onToggle: (target: "backend" | "frontend", running: boolean) => Promise<void>;
  onToggleAll: (action: "start" | "stop") => Promise<void>;
  onPorts: (backendPort: number, frontendPort: number) => Promise<void>;
  onCancel: (jobId: string) => Promise<void>;
  onResume: (jobId: string) => Promise<void>;
  onClearCache: () => Promise<void>;
  onRestore: (versionId: string) => Promise<void>;
  onDeleteVersion: (versionId: string) => Promise<void>;
  onCostMode: (mode: CostMode) => Promise<void>;
  onOpenRepair: (draft: string) => void;
};

export function RuntimeView({ projectId, states, jobs, usage, versions, overview, costMode, busyAction = null, onStates, onToggle, onToggleAll, onPorts, onCancel, onResume, onClearCache, onRestore, onDeleteVersion, onCostMode, onOpenRepair }: RuntimeViewProps) {
  const [logState, setLogState] = useState<{ projectId: string; values: Record<string, string> }>({ projectId, values: {} });
  const logs = logState.projectId === projectId ? logState.values : {};
  const [device, setDevice] = useState<"desktop" | "tablet" | "mobile">("desktop");
  const [maintenanceInfo, setMaintenanceInfo] = useState<MaintenanceSummary | null>(null);
  const [maintenanceBusy, setMaintenanceBusy] = useState(false);
  const [maintenanceError, setMaintenanceError] = useState("");
  const [backendPort, setBackendPort] = useState(() => states.find((item) => item.target === "backend")?.port ?? 8001);
  const [frontendPort, setFrontendPort] = useState(() => states.find((item) => item.target === "frontend")?.port ?? 5174);
  const [technology, setTechnology] = useState<TechnologyStack | null>(null);
  const [jobFilter, setJobFilter] = useState<JobFilter>("all");
  const [showAllJobs, setShowAllJobs] = useState(false);
  const [versionDiff, setVersionDiff] = useState<VersionDiff | null>(null);
  const [diffLoadingId, setDiffLoadingId] = useState<string | null>(null);
  const [diffError, setDiffError] = useState("");
  const [usageRecords, setUsageRecords] = useState<UsageRecord[]>([]);
  const [usageLoading, setUsageLoading] = useState(false);
  const [usageLoaded, setUsageLoaded] = useState(false);
  const [usageError, setUsageError] = useState("");
  const [infrastructure, setInfrastructure] = useState<InfrastructureOverview | null>(null);
  const [infrastructureBusy, setInfrastructureBusy] = useState("");
  const [infrastructureError, setInfrastructureError] = useState("");
  const logCursors = useRef<Record<string, { cursor: number; logId: string }>>({});
  const logCursorProjectId = useRef(projectId);
  const maintenanceBusyRef = useRef(false);
  const infrastructureBusyRef = useRef(false);
  const usageLoadingRef = useRef(false);
  const maintenanceRequestRef = useRef<AbortController | null>(null);
  const diffRequestRef = useRef<AbortController | null>(null);
  const usageRequestRef = useRef<AbortController | null>(null);
  const infrastructureRequestRef = useRef<AbortController | null>(null);

  useEffect(() => () => {
    maintenanceRequestRef.current?.abort();
    maintenanceRequestRef.current = null;
    diffRequestRef.current?.abort();
    diffRequestRef.current = null;
    usageRequestRef.current?.abort();
    usageRequestRef.current = null;
    infrastructureRequestRef.current?.abort();
    infrastructureRequestRef.current = null;
  }, []);

  const refreshRuntime = useCallback(async (signal: AbortSignal = new AbortController().signal) => {
    if (logCursorProjectId.current !== projectId) {
      logCursorProjectId.current = projectId;
      logCursors.current = {};
    }
    const backendCursor = logCursors.current.backend ?? { cursor: 0, logId: "" };
    const frontendCursor = logCursors.current.frontend ?? { cursor: 0, logId: "" };
    const query = new URLSearchParams({
      include_logs: "true",
      backend_cursor: String(backendCursor.cursor),
      backend_log_id: backendCursor.logId,
      frontend_cursor: String(frontendCursor.cursor),
      frontend_log_id: frontendCursor.logId,
    });
    let nextStates: ProcessState[];
    let backend: LogChunk;
    let frontend: LogChunk;
    try {
      const snapshot = await request<RuntimeSnapshot>(`/projects/${projectId}/runtime-snapshot?${query}`, { signal });
      if (!Array.isArray(snapshot.processes) || !snapshot.logs?.backend || !snapshot.logs?.frontend) throw new Error("invalid runtime snapshot");
      nextStates = snapshot.processes;
      backend = snapshot.logs.backend;
      frontend = snapshot.logs.frontend;
    } catch (cause) {
      if (isAbortError(cause) || (cause instanceof ApiError && cause.status !== 404)) throw cause;
      [nextStates, backend, frontend] = await Promise.all([
        request<ProcessState[]>(`/projects/${projectId}/processes`, { signal }),
        request<LogChunk>(`/projects/${projectId}/processes/backend/logs/chunk?cursor=${backendCursor.cursor}&log_id=${encodeURIComponent(backendCursor.logId)}`, { signal }),
        request<LogChunk>(`/projects/${projectId}/processes/frontend/logs/chunk?cursor=${frontendCursor.cursor}&log_id=${encodeURIComponent(frontendCursor.logId)}`, { signal }),
      ]);
    }
    onStates(nextStates);
    const backendPort = nextStates.find((item) => item.target === "backend")?.port;
    const frontendPort = nextStates.find((item) => item.target === "frontend")?.port;
    if (backendPort) setBackendPort(backendPort);
    if (frontendPort) setFrontendPort(frontendPort);
    logCursors.current = {
      backend: { cursor: backend.cursor, logId: backend.log_id },
      frontend: { cursor: frontend.cursor, logId: frontend.log_id },
    };
    setLogState((current) => {
      const previous = current.projectId === projectId ? current.values : {};
      return {
        projectId,
        values: {
          backend: (backend.reset ? backend.logs : `${previous.backend ?? ""}${backend.logs}`).slice(-200_000),
          frontend: (frontend.reset ? frontend.logs : `${previous.frontend ?? ""}${frontend.logs}`).slice(-200_000),
        },
      };
    });
  }, [onStates, projectId]);

  const refreshInfrastructure = useCallback(async (signal?: AbortSignal) => {
    try {
      const next = await request<InfrastructureOverview>(`/projects/${projectId}/infrastructure`, { signal });
      setInfrastructure({
        docker_available: Boolean(next?.docker_available),
        services: Array.isArray(next?.services) ? next.services : [],
        port_settings: Array.isArray(next?.port_settings) ? next.port_settings : [],
        message: next?.message ?? "",
        errors: Array.isArray(next?.errors) ? next.errors : [],
      });
      setInfrastructureError("");
    } catch (cause) {
      if (isAbortError(cause)) return;
      setInfrastructureError(cause instanceof Error ? cause.message : "인프라 상태를 불러오지 못했습니다");
    }
  }, [projectId]);

  useVisibilityPolling(refreshRuntime, { baseDelay: 2000 });
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void request<MaintenanceSummary>(`/projects/${projectId}/maintenance`, { signal: controller.signal }).then(setMaintenanceInfo).catch(() => undefined), 0);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [projectId]);
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void request<TechnologyStack>(`/projects/${projectId}/technology-stack`, { signal: controller.signal }).then(setTechnology).catch(() => undefined), 0);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [projectId]);
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void refreshInfrastructure(controller.signal), 0);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [refreshInfrastructure]);

  const frontend = states.find((state) => state.target === "frontend");
  const resumableJobs = (["generation", "improvement", "repair"] as const)
    .map((kind) => jobs.find((job) => job.kind === kind && job.retry_available && ["failed", "cancelled"].includes(job.status)))
    .filter((job): job is Job => Boolean(job));
  const orderedJobs = useMemo(() => [...jobs].sort((left, right) => {
    const rank = (job: Job) => !["completed", "failed", "cancelled"].includes(job.status) ? 0 : ["failed", "cancelled"].includes(job.status) ? 1 : 2;
    return rank(left) - rank(right) || Date.parse(right.updated_at) - Date.parse(left.updated_at);
  }), [jobs]);
  const filteredJobs = orderedJobs.filter((job) => jobFilter === "all" || (jobFilter === "failed" ? ["failed", "cancelled"].includes(job.status) : job.kind === jobFilter));
  const visibleJobs = showAllJobs ? filteredJobs : filteredJobs.slice(0, 5);

  async function cleanup() {
    if (maintenanceBusyRef.current) return;
    maintenanceBusyRef.current = true;
    const controller = new AbortController();
    maintenanceRequestRef.current = controller;
    setMaintenanceBusy(true);
    setMaintenanceError("");
    try {
      const data = await request<MaintenanceSummary>(`/projects/${projectId}/maintenance`, { method: "POST", body: JSON.stringify({ clear_logs: true, clear_cache: true }), signal: controller.signal });
      setMaintenanceInfo(data);
      setLogState({ projectId, values: {} });
    } catch (cause) {
      if (isAbortError(cause)) return;
      setMaintenanceError(cause instanceof Error ? cause.message : "로그와 캐시를 정리하지 못했습니다");
    } finally {
      if (maintenanceRequestRef.current === controller) {
        maintenanceRequestRef.current = null;
        maintenanceBusyRef.current = false;
        setMaintenanceBusy(false);
      }
    }
  }

  async function showVersionDiff(versionId: string) {
    if (versionDiff?.version_id === versionId) {
      setVersionDiff(null);
      setDiffError("");
      return;
    }
    if (diffRequestRef.current) return;
    const controller = new AbortController();
    diffRequestRef.current = controller;
    setDiffLoadingId(versionId);
    setDiffError("");
    try {
      setVersionDiff(await request<VersionDiff>(`/projects/${projectId}/versions/${versionId}/diff`, { signal: controller.signal }));
    } catch (cause) {
      if (isAbortError(cause)) return;
      setVersionDiff(null);
      setDiffError(cause instanceof Error ? cause.message : "버전 차이를 불러오지 못했습니다");
    } finally {
      if (diffRequestRef.current === controller) {
        diffRequestRef.current = null;
        setDiffLoadingId(null);
      }
    }
  }

  async function loadUsageRecords(reset = false) {
    if (usageLoadingRef.current) return;
    usageLoadingRef.current = true;
    const controller = new AbortController();
    usageRequestRef.current = controller;
    setUsageLoading(true);
    setUsageError("");
    const offset = reset ? 0 : usageRecords.length;
    try {
      const next = await request<UsageRecord[]>(`/projects/${projectId}/usage/records?offset=${offset}&limit=20`, { signal: controller.signal });
      setUsageRecords((current) => reset ? next : [...current, ...next]);
      setUsageLoaded(true);
    } catch (cause) {
      if (isAbortError(cause)) return;
      setUsageError(cause instanceof Error ? cause.message : "사용 내역을 불러오지 못했습니다");
    } finally {
      if (usageRequestRef.current === controller) {
        usageRequestRef.current = null;
        usageLoadingRef.current = false;
        setUsageLoading(false);
      }
    }
  }

  async function manuallyRefreshInfrastructure() {
    if (infrastructureBusyRef.current) return;
    infrastructureBusyRef.current = true;
    const controller = new AbortController();
    infrastructureRequestRef.current = controller;
    setInfrastructureBusy("refresh");
    try {
      await refreshInfrastructure(controller.signal);
    } finally {
      if (infrastructureRequestRef.current === controller) {
        infrastructureRequestRef.current = null;
        infrastructureBusyRef.current = false;
        setInfrastructureBusy("");
      }
    }
  }

  async function controlInfrastructure(item: InfrastructureServiceState, action: "start" | "stop") {
    if (infrastructureBusyRef.current) return;
    infrastructureBusyRef.current = true;
    const controller = new AbortController();
    infrastructureRequestRef.current = controller;
    const key = `${item.source}:${item.name}`;
    setInfrastructureBusy(key);
    setInfrastructureError("");
    try {
      setInfrastructure(await request<InfrastructureOverview>(`/projects/${projectId}/infrastructure/control`, { method: "POST", body: JSON.stringify({ source: item.source, service: item.name, action }), signal: controller.signal }));
    } catch (cause) {
      if (isAbortError(cause)) return;
      setInfrastructureError(cause instanceof Error ? cause.message : "인프라 상태를 변경하지 못했습니다");
    } finally {
      if (infrastructureRequestRef.current === controller) {
        infrastructureRequestRef.current = null;
        infrastructureBusyRef.current = false;
        setInfrastructureBusy("");
      }
    }
  }

  async function saveInfrastructurePorts(values: Record<string, number>) {
    if (infrastructureBusyRef.current) return;
    infrastructureBusyRef.current = true;
    const controller = new AbortController();
    infrastructureRequestRef.current = controller;
    setInfrastructureBusy("ports");
    setInfrastructureError("");
    try {
      setInfrastructure(await request<InfrastructureOverview>(`/projects/${projectId}/infrastructure/ports`, { method: "PUT", body: JSON.stringify({ values }), signal: controller.signal }));
      await refreshRuntime(controller.signal);
    } catch (cause) {
      if (isAbortError(cause)) return;
      setInfrastructureError(cause instanceof Error ? cause.message : "인프라 포트를 저장하지 못했습니다");
    } finally {
      if (infrastructureRequestRef.current === controller) {
        infrastructureRequestRef.current = null;
        infrastructureBusyRef.current = false;
        setInfrastructureBusy("");
      }
    }
  }

  return <div className="runtime-page">
    <RuntimeBulkControls states={states} busy={Boolean(busyAction)} startingAction={busyAction === "process-start-all"} onToggleAll={onToggleAll} />
    <RuntimePreview frontend={frontend} device={device} onDevice={setDevice} />
    <RuntimePortSettings backendPort={backendPort} frontendPort={frontendPort} busy={Boolean(busyAction)} saving={busyAction === "ports"} onBackendPort={setBackendPort} onFrontendPort={setFrontendPort} onSave={() => onPorts(backendPort, frontendPort)} />
    {technology && <TechnologyStackPanel value={technology} />}
    <InfrastructureStatusPanel projectId={projectId} value={infrastructure} busy={infrastructureBusy || (busyAction ? "runtime" : "")} error={infrastructureError} onRefresh={manuallyRefreshInfrastructure} onControl={controlInfrastructure} onPorts={saveInfrastructurePorts} />
    <details className="version-manager"><summary>저장된 버전 관리 <b>{versions.length}</b></summary><div>{versions.length ? versions.map((version) => <div className="version-entry" key={version.id}><article><span><strong>{version.label}</strong><small>{new Date(version.created_at).toLocaleString("ko-KR")}</small></span><button disabled={Boolean(busyAction) || Boolean(diffLoadingId)} onClick={() => void showVersionDiff(version.id)}>{diffLoadingId === version.id ? "비교 중" : versionDiff?.version_id === version.id ? "차이 닫기" : "차이 보기"}</button><button disabled={Boolean(busyAction) || Boolean(diffLoadingId)} onClick={() => void onRestore(version.id)}>{busyAction === `restore-${version.id}` ? "복원 중…" : "복원"}</button><button disabled={Boolean(busyAction) || Boolean(diffLoadingId)} className="danger" onClick={() => void onDeleteVersion(version.id)}>삭제</button></article>{versionDiff?.version_id === version.id && <VersionDiffPanel value={versionDiff} />}</div>) : <p>저장된 버전이 없습니다.</p>}{diffError && <p className="version-diff-error">{diffError}</p>}</div></details>
    <div className="runtime-cards">{states.map((state) => <ProcessCard key={state.target} state={state} logs={logs[state.target]} busy={Boolean(busyAction)} onToggle={onToggle} onOpenRepair={onOpenRepair} />)}</div>
    {resumableJobs.length > 0 && <section className="resume-jobs"><div className="resume-heading"><strong>다시 이어갈 수 있는 작업</strong><small>저장된 결과가 없으면 재시도 시 LLM 비용이 발생할 수 있습니다.</small></div>{resumableJobs.map((job) => <article key={job.id}><div><strong>{job.kind === "repair" ? "오류 수정" : job.kind === "improvement" ? "개선 적용" : "최초 생성"} · {job.cached_result_available ? "결과 저장됨" : "새 요청 필요"}</strong><small>{job.error || job.message} · {new Date(job.updated_at).toLocaleString("ko-KR")}</small></div><button disabled={Boolean(busyAction)} onClick={() => void onResume(job.id)}>{busyAction === `resume-${job.id}` ? "재개 중…" : job.cached_result_available ? "저장된 결과 적용" : "LLM 다시 요청"}</button></article>)}</section>}
    <section className="history">
      <div className="health-strip"><strong>통합 상태</strong><span>백엔드 {states.find((item) => item.target === "backend")?.phase === "ready" ? "준비 완료" : "중지"}</span><span>프론트 {frontend?.phase === "ready" ? "준비 완료" : "중지"}</span><span>환경변수 {overview?.missing_environment.length ? `${overview.missing_environment.length}개 누락` : "정상"}</span><span>HTTP {overview?.health.length ? `${overview.health.filter((item) => item.healthy).length}/${overview.health.length} 정상` : "미선언"}</span></div>
      <div className="section-heading"><div><h2>LLM 사용량</h2><p>{usage ? `${usage.requests}회 · 입력 ${usage.input_tokens.toLocaleString()} · 출력 ${usage.output_tokens.toLocaleString()} · 캐시 입력 ${usage.cached_input_tokens.toLocaleString()} 토큰` : "기록된 사용량이 없습니다."}</p></div><button disabled={Boolean(busyAction)} onClick={() => void onClearCache()}>{busyAction === "cache" ? "비우는 중…" : "생성 캐시 비우기"}</button></div>
      {usage?.by_kind && <div className="usage-breakdown">{Object.entries(usage.by_kind).map(([kind, totals]) => <span key={kind}><strong>{({ planning: "기획", improvement_planning: "개선 기획", generation: "최초 생성", improvement_generation: "개선 생성", repair: "오류 수정" } as Record<string, string>)[kind] || kind}</strong>{totals.requests}회 · 입력 {totals.input_tokens.toLocaleString()}</span>)}</div>}
      <details className="usage-history" onToggle={(event) => { if (event.currentTarget.open && !usageLoaded && !usageLoading) void loadUsageRecords(true); }}><summary>요청별 토큰 상세 <b>{usage?.requests ?? 0}</b></summary><div>{usageRecords.map((record) => <UsageRecordRow key={record.id} value={record} />)}{usageLoaded && usageRecords.length === 0 && <p>기록된 LLM 요청이 없습니다.</p>}{usageError && <p className="usage-error">{usageError}</p>}{usageLoading && <p>사용 내역을 불러오는 중입니다.</p>}{usage && usageRecords.length < usage.requests && !usageLoading && <button className="usage-more" onClick={() => void loadUsageRecords()}>이전 요청 더 보기</button>}<small>실제 청구 금액은 각 LLM 공급자의 결제 내역에서 확인하세요.</small></div></details>
      <div className="cost-modes"><span>생성 품질·비용</span><small>{({ economy: "핵심 흐름 중심의 간결한 MVP", balanced: "완성도와 비용의 균형", quality: "복잡한 풀스택 서비스는 영역별 최대 2회 생성" } as const)[costMode]}</small>{(["economy", "balanced", "quality"] as const).map((mode) => <button disabled={Boolean(busyAction)} className={costMode === mode ? "active" : ""} key={mode} onClick={() => void onCostMode(mode)} title={({ economy: "핵심 흐름 중심의 간결한 MVP", balanced: "완성도와 비용의 균형", quality: "스택별 규칙과 자체 점검을 강화하며 복잡한 풀스택 서비스는 최대 2회 요청" } as const)[mode]}>{({ economy: "절약", balanced: "균형", quality: "품질" } as const)[mode]}</button>)}</div>
      <div className="section-heading"><div><h2>저장공간</h2><p>{maintenanceInfo ? `전체 ${formatBytes(maintenanceInfo.disk_bytes)} · 버전 ${maintenanceInfo.version_count}개 · 로그 ${formatBytes(maintenanceInfo.logs_bytes)}` : "계산 중"}</p>{maintenanceError && <small className="usage-error">{maintenanceError}</small>}</div><button disabled={Boolean(busyAction) || maintenanceBusy} onClick={() => void cleanup()}>{maintenanceBusy ? "정리 중…" : "로그·캐시 정리"}</button></div>
      <div className="job-history-heading"><div><h2>작업 내역</h2><small>진행 중과 실패 작업을 먼저 표시합니다.</small></div><div>{(["all", "generation", "improvement", "repair", "failed"] as const).map((filter) => <button className={jobFilter === filter ? "active" : ""} key={filter} onClick={() => { setJobFilter(filter); setShowAllJobs(false); }}>{({ all: "전체", generation: "생성", improvement: "개선", repair: "오류수정", failed: "실패" } as const)[filter]}</button>)}</div></div>
      <div className="job-history">{visibleJobs.length === 0 ? <p>조건에 맞는 작업이 없습니다.</p> : visibleJobs.map((job) => <div className="job-row" key={job.id}><span className={`job-dot ${job.status}`} /><div><strong>{({ generation: "최초 생성", improvement: "개선 적용", repair: "오류 수정" } as const)[job.kind]} · {job.message}</strong><small>{job.error && `${job.error} · `}{new Date(job.updated_at).toLocaleString("ko-KR")}</small>{job.generation_report && <GenerationCoverage value={job.generation_report} />}{Boolean(job.diagnostics?.length) && <details className="job-diagnostics"><summary>비차단 진단 {job.diagnostics?.length}건</summary><ul>{job.diagnostics?.map((item) => <li key={item}>{item}</li>)}</ul></details>}</div>{!["completed", "failed", "cancelled"].includes(job.status) ? <button disabled={Boolean(busyAction)} onClick={() => void onCancel(job.id)}>{busyAction === `cancel-${job.id}` ? "취소 중…" : "취소"}</button> : <code>{job.status}</code>}</div>)}</div>
      {filteredJobs.length > 5 && <button className="show-all-jobs" onClick={() => setShowAllJobs((value) => !value)}>{showAllJobs ? "최근 작업만 보기" : `이전 작업 ${filteredJobs.length - 5}개 더 보기`}</button>}
    </section>
  </div>;
}
