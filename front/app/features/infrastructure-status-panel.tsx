"use client";

import { useEffect, useRef, useState } from "react";
import { apiRequest as request, isAbortError } from "../lib/api";
import type { InfrastructureLogs, InfrastructureOverview, InfrastructureServiceState } from "../studio-types";

type Props = {
  projectId: string;
  value: InfrastructureOverview | null;
  busy: string;
  error: string;
  onRefresh: () => Promise<void>;
  onControl: (item: InfrastructureServiceState, action: "start" | "stop") => Promise<void>;
  onPorts: (values: Record<string, number>) => Promise<void>;
};

export function InfrastructureStatusPanel({ projectId, value, busy, error, onRefresh, onControl, onPorts }: Props) {
  const services = value?.services ?? [];
  const portSettings = value?.port_settings ?? [];
  const portKey = portSettings.map((item) => `${item.key}:${item.value}`).join("|");
  const [openLog, setOpenLog] = useState("");
  const [logs, setLogs] = useState("");
  const [logError, setLogError] = useState("");
  const [logLoading, setLogLoading] = useState(false);
  const logRequest = useRef<AbortController | null>(null);

  useEffect(() => () => logRequest.current?.abort(), []);

  async function toggleLogs(item: InfrastructureServiceState) {
    const key = `${item.source}:${item.name}`;
    if (openLog === key) {
      logRequest.current?.abort();
      setOpenLog("");
      return;
    }
    logRequest.current?.abort();
    const controller = new AbortController();
    logRequest.current = controller;
    setOpenLog(key);
    setLogs("");
    setLogError("");
    setLogLoading(true);
    try {
      const result = await request<InfrastructureLogs>(
        `/projects/${projectId}/infrastructure/logs?source=${encodeURIComponent(item.source)}&service=${encodeURIComponent(item.name)}&tail=200`,
        { signal: controller.signal },
      );
      setLogs(result.logs);
    } catch (cause) {
      if (!isAbortError(cause)) setLogError(cause instanceof Error ? cause.message : "컨테이너 로그를 불러오지 못했습니다.");
    } finally {
      if (logRequest.current === controller) {
        logRequest.current = null;
        setLogLoading(false);
      }
    }
  }

  return <details className="infrastructure-panel">
    <summary><span><strong>인프라 상태</strong><small>전체 실행 전 필요한 Docker 의존성을 먼저 준비합니다.</small></span><b>{services.filter((item) => item.running).length}/{services.length}</b></summary>
    <div>
      <div className="infrastructure-heading"><span>{value?.docker_available ? "Docker 연결됨" : "Docker 제어 불가"}</span><button disabled={Boolean(busy)} onClick={() => void onRefresh()}>{busy === "refresh" ? "확인 중…" : "상태 새로고침"}</button></div>
      {portSettings.length > 0 && <InfrastructurePortEditor key={portKey} items={portSettings} disabled={Boolean(busy)} saving={busy === "ports"} onSave={onPorts} />}
      {services.map((item) => {
        const key = `${item.source}:${item.name}`;
        const failed = item.health === "unhealthy" || /exited|dead|restarting/i.test(item.status);
        return <div className="infrastructure-entry" key={`${item.kind}:${key}`}>
          <article>
            <i className={failed ? "failed" : item.running ? "running" : "stopped"} />
            <span><strong>{item.name}</strong><small>{item.kind === "docker" ? `Docker Compose · ${item.source}` : `외부 서비스 · ${item.source}`}{item.ports.length ? ` · ${item.ports.join(", ")}` : ""}</small></span>
            <code>{item.health || item.status}{!item.running && item.exit_code !== null && item.exit_code !== undefined ? ` · exit ${item.exit_code}` : ""}</code>
            <div className="infrastructure-actions">
              {item.kind === "docker" && <button disabled={logLoading && openLog === key} onClick={() => void toggleLogs(item)}>{openLog === key ? "로그 닫기" : "로그"}</button>}
              {item.controllable && <button disabled={Boolean(busy)} className={item.running ? "stop" : "start"} onClick={() => void onControl(item, item.running ? "stop" : "start")}>{busy === key ? "처리 중" : item.running ? "중지" : "시작"}</button>}
            </div>
          </article>
          {openLog === key && <pre className="infrastructure-logs">{logLoading ? "최근 로그를 불러오는 중입니다..." : logError || logs || "표시할 로그가 없습니다."}</pre>}
        </div>;
      })}
      {value?.message && <p>{value.message}</p>}
      {value?.errors?.length ? <ul className="infrastructure-errors">{value.errors.map((item) => <li key={item}>{item}</li>)}</ul> : null}
      {error && <p className="infrastructure-error">{error}</p>}
      {!value && !error && <p>인프라 상태를 확인하는 중입니다.</p>}
    </div>
  </details>;
}

function InfrastructurePortEditor({ items, disabled, saving, onSave }: { items: InfrastructureOverview["port_settings"]; disabled: boolean; saving: boolean; onSave: (values: Record<string, number>) => Promise<void> }) {
  const [values, setValues] = useState<Record<string, number>>(() => Object.fromEntries(items.map((item) => [item.key, item.value])));
  return <section className="infrastructure-ports"><div><strong>인프라 포트</strong><small>컨테이너를 중지한 뒤 저장하세요. 충돌 여부를 자동 확인합니다.</small></div>{items.map((item) => <label key={item.key}>{item.key}<input disabled={disabled} type="number" min="1024" max="65535" value={values[item.key]} onChange={(event) => setValues((current) => ({ ...current, [item.key]: Number(event.target.value) }))} /></label>)}<button disabled={disabled} onClick={() => void onSave(values)}>{saving ? "저장 중" : "포트 저장"}</button></section>;
}
