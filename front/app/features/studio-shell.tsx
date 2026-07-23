import { useEffect, useState } from "react";
import { apiRequest, isAbortError } from "../lib/api";
import type { LlmActivity, Notification, Project, ProjectOverview, SearchResult } from "../studio-types";
import { projectStatusClass, projectStatusLabel, StatusPill } from "./studio-shared";

export function StudioSidebar({ projects, selectedId, settingsOpen, loading, connection, activity, overviews = {}, onSelect, onCreate, onImport, onSettings, onTrash }: {
  projects: Project[]; selectedId: string | null; settingsOpen: boolean; loading: boolean; connection: "checking" | "online" | "offline"; activity: LlmActivity;
  onSelect: (id: string, target?: "runtime") => void; onCreate: () => void; onImport: () => void; onSettings: () => void; onTrash: () => void;
  overviews?: Record<string, ProjectOverview>;
}) {
  const error = connection === "offline";
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const normalized = query.trim().toLocaleLowerCase("ko-KR");
  const localProjects = projects.filter((project) => !normalized || `${project.name} ${project.id} ${project.description}`.toLocaleLowerCase("ko-KR").includes(normalized));
  useEffect(() => {
    if (query.trim().length < 2) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => { setSearching(true); void apiRequest<SearchResult[]>(`/search?q=${encodeURIComponent(query.trim())}&limit=30`, { signal: controller.signal }).then(setResults).catch((cause) => { if (!isAbortError(cause)) setResults([]); }).finally(() => { if (!controller.signal.aborted) setSearching(false); }); }, 250);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [query]);
  const clearSearch = () => { setQuery(""); setResults([]); setSearching(false); };
  const select = (projectId: string, target?: "runtime") => { clearSearch(); onSelect(projectId, target); };
  return <aside className="sidebar"><div className="brand"><span className="brand-mark">D</span><div><strong>도라에몽</strong><small>도구를 꺼내줘요</small></div></div><button className="new-button" onClick={onCreate}><span>＋</span> 새 서비스</button><button className="import-button" onClick={onImport}><span>⇧</span> ZIP 가져오기</button><div className="sidebar-search"><span>⌕</span><input aria-label="서비스·작업 검색" value={query} onChange={(event) => { const value = event.target.value; setQuery(value); if (value.trim().length < 2) { setResults([]); setSearching(false); } }} placeholder="서비스·작업 검색" />{query && <button aria-label="검색 지우기" onClick={clearSearch}>×</button>}</div><div className="sidebar-label"><span>{query ? "검색 결과" : "서비스"}</span><span>{query.trim().length >= 2 ? results.length : localProjects.length}</span></div>{query.trim().length >= 2 ? <nav className="project-list search-results" aria-label="검색 결과">{results.map((result, index) => <button key={`${result.kind}-${result.project_id}-${index}`} className="search-result" onClick={() => select(result.project_id, result.kind === "job" ? "runtime" : undefined)}><i className={result.kind}>{result.kind === "job" ? "작업" : "서비스"}</i><span><strong>{result.title}</strong><small>{result.kind === "job" ? `${result.project_name} · ${result.status}` : result.subtitle}</small></span></button>)}{searching && <p className="sidebar-empty">검색 중…</p>}{!searching && results.length === 0 && <p className="sidebar-empty">일치하는 서비스나 작업이 없습니다.</p>}</nav> : <nav className="project-list" aria-label="서비스 목록">{localProjects.map((project) => { const working = activity.busy && activity.project_id === project.id; return <button key={project.id} className={`project-item ${selectedId === project.id && !settingsOpen ? "active" : ""} ${working ? "working" : ""}`} onClick={() => select(project.id)}><span className={`status-dot ${working ? "generating" : projectStatusClass(project, overviews[project.id])}`} /><span><strong>{project.name}</strong>{working ? <small className="project-work"><b>LLM 작업 중</b><span>{project.id} · 약 {activity.estimated_input_tokens.toLocaleString()} 입력 토큰</span></small> : <small>{projectStatusLabel(project, overviews[project.id])}</small>}</span></button>; })}{!loading && localProjects.length === 0 && <p className="sidebar-empty">{query ? "일치하는 서비스가 없습니다." : "아직 만든 서비스가 없습니다."}</p>}</nav>}<button className={`sidebar-settings ${settingsOpen ? "active" : ""}`} onClick={onSettings}>⚙ Doraemon 설정</button><button className="trash-open" onClick={onTrash}>휴지통</button><div className="connection"><span className={error ? "offline" : "online"} />{error ? "연결 확인 필요" : "로컬 API 연결됨"}</div></aside>;
}

export function StudioHeader({ project, notifications, busyAction = "", onRead, onFolder, onRename, onClone, onTrash, onRefresh }: {
  project: Project; notifications: Notification[]; busyAction?: string; onRead: () => void; onFolder: () => void; onRename: () => void; onClone: () => void; onTrash: () => void; onRefresh: () => void;
}) {
  const [descriptionOpen, setDescriptionOpen] = useState(false);
  const unread = notifications.filter((item) => !item.read).length;
  const hasLongDescription = project.description.length > 100 || project.description.includes("\n");
  const busy = Boolean(busyAction);
  return <header className="workspace-header" aria-busy={busy}>
    <div className="header-copy">
      <div className="eyebrow">DORAEMON / {project.id}</div><h1>{project.name}</h1>
      <div className={`service-description ${descriptionOpen ? "expanded" : ""}`}><p id="service-description">{project.description}</p>{hasLongDescription && <button type="button" aria-expanded={descriptionOpen} aria-controls="service-description" onClick={() => setDescriptionOpen((value) => !value)}>{descriptionOpen ? "접기" : "전체 보기"}</button>}</div>
    </div>
    <div className="header-actions">
      <StatusPill status={project.status} />
      <details key={project.id} className="notification-center"><summary>알림{unread > 0 && <b>{unread}</b>}</summary><div><header><strong>작업 알림</strong><button disabled={busy} onClick={onRead}>{busyAction === "read-notifications" ? "처리 중…" : "모두 읽음"}</button></header>{notifications.length ? notifications.slice(0, 8).map((item) => <article className={item.read ? "read" : ""} key={item.id}><i className={item.level}/><span><strong>{item.title}</strong><small>{item.message}</small></span></article>) : <p>새 알림이 없습니다.</p>}</div></details>
      <button disabled={busy} onClick={onFolder}>{busyAction === "open-folder" ? "여는 중…" : "폴더"}</button>
      <button disabled={busy} onClick={onRename}>{busyAction === "rename" ? "변경 중…" : "이름 변경"}</button>
      <button disabled={busy} onClick={onClone}>{busyAction === "clone" ? "복제 중…" : "복제"}</button>
      <button disabled={busy} className="danger-text" onClick={onTrash}>{busyAction === "trash" ? "이동 중…" : "휴지통"}</button>
      <button disabled={busy} className="icon-button" title="새로고침" onClick={onRefresh}>↻</button>
    </div>
  </header>;
}
