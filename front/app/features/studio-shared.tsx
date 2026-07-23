import type { Job, Message, Plan, Project, ProjectOverview } from "../studio-types";

export function EmptyState({ loading, onCreate }: { loading: boolean; onCreate: () => void }) {
  return <div className="empty-workspace"><span>✦</span><h1>{loading ? "Doraemon을 준비하고 있어요" : "첫 서비스를 만들어보세요"}</h1><p>{loading ? "잠시만 기다려주세요." : "아이디어를 말하면 기획부터 구현과 실행까지 함께 진행합니다."}</p>{!loading && <button onClick={onCreate}>새 서비스 시작</button>}</div>;
}

export function StatusPill({ status }: { status: Project["status"] }) {
  return <span className={`status-pill ${status}`}><i />{statusLabel(status)}</span>;
}

export function StagePill({ stage }: { stage?: Plan["draft"]["stage"] }) {
  const text = !stage ? "대기" : stage === "discovery" ? "요구사항 탐색" : stage === "design" ? "서비스 명세" : stage === "technical" ? "기술 명세" : "최종 검토";
  return <span className={`stage-pill ${stage ?? "waiting"}`}>{text}</span>;
}

export function JobProgress({ job }: { job: Job }) {
  const steps = ["queued", "planning", "generating", "writing", "completed"];
  const progress = Math.max(8, ((steps.indexOf(job.status) + 1) / steps.length) * 100);
  return <div className="job-progress"><div><span>{job.message}</span><b>{Math.round(progress)}%</b></div><i><span style={{ width: `${progress}%` }} /></i></div>;
}

export function statusLabel(status: Project["status"]) {
  return ({ draft: "기획 중", generating: "생성 중", ready: "실행 가능", error: "확인 필요" } as const)[status];
}

export function projectStatusClass(project: Project, overview?: ProjectOverview) {
  if (overview?.missing_environment.length) return "error";
  if (overview?.backend_running || overview?.frontend_running) return "ready";
  return project.status;
}

export function projectStatusLabel(project: Project, overview?: ProjectOverview) {
  if (overview?.missing_environment.length) return `환경변수 ${overview.missing_environment.length}개 누락`;
  if (overview?.backend_running && overview?.frontend_running) return "전체 실행 중";
  if (overview?.backend_running) return "백엔드 실행 중";
  if (overview?.frontend_running) return "프론트 실행 중";
  return statusLabel(project.status);
}

export function compactChatMessage(message: Message) {
  if (message.role === "user" || message.content.length <= 3000) return message.content;
  return `${message.content.slice(0, 900).trim()}…\n\n이전 형식의 긴 명세 응답입니다. 전체 내용은 오른쪽 명세 패널에서 확인할 수 있습니다.`;
}

export function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}
