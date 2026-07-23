"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { apiRequest, apiUrl, isAbortError } from "../lib/api";

type ProbeResult = { url: string; status_code: number; headers: Record<string, string>; body: string };
type DiagnosticItem = { level: "info" | "warning" | "error"; category: string; message: string };
type DiagnosticReport = { security: DiagnosticItem[]; consistency: DiagnosticItem[]; external_services: DiagnosticItem[] };
type Database = { path: string; tables: string[] };

export function ToolsView({ projectId, onError }: { projectId: string; onError: (message: string) => void }) {
  const [method, setMethod] = useState("GET");
  const [target, setTarget] = useState("backend");
  const [path, setPath] = useState("/");
  const [body, setBody] = useState("");
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const [diagnostics, setDiagnostics] = useState<DiagnosticReport | null>(null);
  const [databases, setDatabases] = useState<Database[]>([]);
  const [database, setDatabase] = useState("");
  const [table, setTable] = useState("");
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [busyAction, setBusyAction] = useState<"probe" | "diagnostics" | "rows" | "">("");
  const busyRef = useRef(false);
  const actionRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void apiRequest<Database[]>(`/projects/${projectId}/sqlite`, { signal: controller.signal })
      .then(setDatabases)
      .catch((cause) => { if (!isAbortError(cause)) onError(String(cause)); });
    return () => {
      controller.abort();
      actionRef.current?.abort();
      actionRef.current = null;
      busyRef.current = false;
    };
  }, [projectId, onError]);

  async function runAction(key: "probe" | "diagnostics" | "rows", task: (signal: AbortSignal) => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true;
    const controller = new AbortController();
    actionRef.current = controller;
    setBusyAction(key);
    try { await task(controller.signal); }
    catch (error) { if (!isAbortError(error)) onError(error instanceof Error ? error.message : String(error)); }
    finally {
      if (actionRef.current === controller) {
        actionRef.current = null; busyRef.current = false; setBusyAction("");
      }
    }
  }

  async function runProbe(event: FormEvent) {
    event.preventDefault();
    await runAction("probe", async (signal) => {
      let parsed: unknown = undefined;
      if (body.trim()) parsed = JSON.parse(body);
      setProbe(await apiRequest<ProbeResult>(`/projects/${projectId}/api-probe`, { method: "POST", body: JSON.stringify({ method, target, path, body: parsed }), signal }));
    });
  }

  async function runDiagnostics() {
    await runAction("diagnostics", async (signal) => setDiagnostics(await apiRequest<DiagnosticReport>(`/projects/${projectId}/diagnostics`, { signal })));
  }

  async function loadRows(nextDatabase = database, nextTable = table) {
    if (!nextDatabase || !nextTable) return;
    await runAction("rows", async (signal) => setRows(await apiRequest<Record<string, unknown>[]>(`/projects/${projectId}/sqlite/rows?path=${encodeURIComponent(nextDatabase)}&table=${encodeURIComponent(nextTable)}`, { signal })));
  }


  const findings = diagnostics ? [...diagnostics.security, ...diagnostics.consistency, ...diagnostics.external_services] : [];
  const selectedDatabase = databases.find((item) => item.path === database);
  const busy = Boolean(busyAction);
  return <div className="tools-page" aria-busy={busy}>
    <section className="tool-card"><div className="section-heading"><div><h2>로컬 API 검사</h2><p>생성된 서비스의 실제 응답을 Doraemon 안에서 확인합니다.</p></div></div>
      <form className="probe-form" onSubmit={runProbe}><select disabled={busy} value={target} onChange={(e) => setTarget(e.target.value)}><option value="backend">백엔드</option><option value="frontend">프론트엔드</option></select><select disabled={busy} value={method} onChange={(e) => setMethod(e.target.value)}>{["GET","POST","PUT","PATCH","DELETE"].map((item) => <option key={item}>{item}</option>)}</select><input disabled={busy} value={path} onChange={(e) => setPath(e.target.value)} placeholder="/api/health" /><button disabled={busy}>{busyAction === "probe" ? "요청 중…" : "요청"}</button><textarea disabled={busy} value={body} onChange={(e) => setBody(e.target.value)} placeholder='선택: JSON 본문 {"name":"example"}' /></form>
      {probe && <pre className="tool-output">{probe.status_code} {probe.url}{"\n\n"}{probe.body}</pre>}
    </section>
    <section className="tool-card"><div className="section-heading"><div><h2>진단</h2><p>명세 불일치, 노출된 비밀값, CORS, 외부 서비스 연결을 검사합니다.</p></div><button disabled={busy} onClick={() => void runDiagnostics()}>{busyAction === "diagnostics" ? "검사 중…" : "검사 실행"}</button></div>{diagnostics && <div className="finding-list">{findings.length ? findings.map((item, index) => <div className={`finding ${item.level}`} key={`${item.category}-${index}`}><strong>{item.category}</strong><span>{item.message}</span></div>) : <p>발견된 문제가 없습니다.</p>}</div>}</section>
    <section className="tool-card"><div className="section-heading"><div><h2>SQLite 조회</h2><p>데이터를 변경하지 않는 읽기 전용 조회입니다.</p></div></div><div className="sqlite-controls"><select disabled={busy} value={database} onChange={(e) => { setDatabase(e.target.value); setTable(""); setRows([]); }}><option value="">DB 선택</option>{databases.map((item) => <option key={item.path}>{item.path}</option>)}</select><select disabled={busy} value={table} onChange={(e) => setTable(e.target.value)}><option value="">테이블 선택</option>{selectedDatabase?.tables.map((item) => <option key={item}>{item}</option>)}</select><button disabled={busy || !database || !table} onClick={() => void loadRows()}>{busyAction === "rows" ? "조회 중…" : "조회"}</button></div>{rows.length > 0 && <div className="table-scroll"><table><thead><tr>{Object.keys(rows[0]).map((key) => <th key={key}>{key}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{Object.values(row).map((value, cell) => <td key={cell}>{String(value ?? "")}</td>)}</tr>)}</tbody></table></div>}</section>
    <section className="tool-card"><div className="section-heading"><div><h2>프로젝트 내보내기</h2><p>비밀값과 의존성 폴더를 제외한 소스 ZIP을 만듭니다.</p></div><button onClick={() => { const form = document.createElement("form"); form.method = "POST"; form.action = apiUrl(`/projects/${projectId}/export`); document.body.append(form); form.submit(); form.remove(); }}>ZIP 다운로드</button></div></section>
  </div>;
}
