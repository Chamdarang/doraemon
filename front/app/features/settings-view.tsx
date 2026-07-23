"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { apiRequest, isAbortError } from "../lib/api";

type Provider = "openai" | "anthropic" | "gemini" | "openrouter" | "ollama" | "custom";
type Settings = {
  default_cost_mode: "economy" | "balanced" | "quality";
  keep_versions: number;
  log_tail_lines: number;
  log_max_bytes: number;
  notification_retention_days: number;
  notification_max_items: number;
  llm_provider: Provider;
  llm_model: string;
  llm_base_url: string;
  llm_api_key_configured: boolean;
  llm_api_key_providers: string[];
  llm_max_output_tokens: number;
  llm_profiles: Record<string, { model: string; base_url: string }>;
};
type ConnectionResult = { provider: string; model: string; reachable: boolean; model_found: boolean; structured_output: boolean | null; detail: string };
type RecoveryStatus = { recovered_count: number; events: { path: string; recovered_at: string }[] };
type PortConflictReport = {
  conflicts: { port: number; owners: string[] }[];
  changes: { project_id: string; target: "backend" | "frontend"; previous_port: number; port: number }[];
  unresolved_projects: string[];
};

const presets: Record<Provider, { url: string; model: string }> = {
  openai: { url: "", model: "gpt-5.4-mini" },
  anthropic: { url: "https://api.anthropic.com/v1/messages", model: "claude-sonnet-4-6" },
  gemini: { url: "https://generativelanguage.googleapis.com/v1beta", model: "gemini-3.5-flash" },
  openrouter: { url: "https://openrouter.ai/api/v1", model: "anthropic/claude-sonnet-4.6" },
  ollama: { url: "http://localhost:11434/v1", model: "qwen3-coder" },
  custom: { url: "", model: "" },
};

export function SettingsView({ onError }: { onError: (message: string) => void }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [saved, setSaved] = useState(false);
  const [busyAction, setBusyAction] = useState<"save" | "test" | "clear" | "ports" | "">("");
  const [connection, setConnection] = useState<ConnectionResult | null>(null);
  const [recovery, setRecovery] = useState<RecoveryStatus>({ recovered_count: 0, events: [] });
  const [ports, setPorts] = useState<PortConflictReport | null>(null);
  const busyRef = useRef(false);
  const actionRef = useRef<AbortController | null>(null);
  const savedTimerRef = useRef<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void apiRequest<Settings>("/settings", { signal: controller.signal })
      .then(setSettings)
      .catch((cause) => { if (!isAbortError(cause)) onError(String(cause)); });
    void apiRequest<RecoveryStatus>("/settings/recovery-status", { signal: controller.signal })
      .then((next) => { if (Array.isArray(next?.events)) setRecovery(next); })
      .catch((cause) => { if (!isAbortError(cause)) console.warn("Recovery status unavailable", cause); });
    void apiRequest<PortConflictReport>("/settings/port-conflicts", { signal: controller.signal })
      .then((next) => { if (Array.isArray(next?.conflicts)) setPorts(next); })
      .catch((cause) => { if (!isAbortError(cause)) console.warn("Port scan unavailable", cause); });
    return () => {
      controller.abort();
      actionRef.current?.abort();
      actionRef.current = null;
      if (savedTimerRef.current !== null) window.clearTimeout(savedTimerRef.current);
      busyRef.current = false;
    };
  }, [onError]);

  async function persist(current: Settings, signal: AbortSignal) {
    const next = await apiRequest<Settings>("/settings", {
      method: "PUT",
      body: JSON.stringify({ ...current, llm_api_key: apiKey || null }),
      signal,
    });
    setSettings(next);
    setApiKey("");
    return next;
  }

  async function runAction(key: "save" | "test" | "clear" | "ports", task: (signal: AbortSignal) => Promise<void>) {
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

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!settings) return;
    await runAction("save", async (signal) => {
      await persist(settings, signal);
      setSaved(true);
      if (savedTimerRef.current !== null) window.clearTimeout(savedTimerRef.current);
      savedTimerRef.current = window.setTimeout(() => setSaved(false), 1600);
    });
  }

  async function testConnection() {
    if (!settings) return;
    await runAction("test", async (signal) => {
      setConnection(null);
      await persist(settings, signal);
      setConnection(await apiRequest<ConnectionResult>("/settings/llm/test", { method: "POST", signal }));
    });
  }

  async function clearKey() {
    if (!settings) return;
    await runAction("clear", async (signal) => {
      const next = await apiRequest<Settings>("/settings", {
        method: "PUT",
        body: JSON.stringify({ ...settings, clear_llm_api_key: true }),
        signal,
      });
      setSettings(next);
      setApiKey("");
      setConnection(null);
    });
  }

  async function resolvePorts() {
    await runAction("ports", async (signal) => {
      setPorts(await apiRequest<PortConflictReport>("/settings/port-conflicts/resolve", { method: "POST", signal }));
    });
  }

  function selectProvider(provider: Provider) {
    if (!settings) return;
    const profiles = {
      ...settings.llm_profiles,
      [settings.llm_provider]: { model: settings.llm_model, base_url: settings.llm_base_url },
    };
    const savedProfile = settings.llm_profiles[provider] as { model: string; base_url: string } | undefined;
    const preset = presets[provider];
    setApiKey("");
    setConnection(null);
    setSettings({
      ...settings,
      llm_provider: provider,
      llm_base_url: savedProfile?.base_url ?? preset.url,
      llm_model: savedProfile?.model ?? preset.model,
      llm_api_key_configured: settings.llm_api_key_providers.includes(provider),
      llm_profiles: profiles,
    });
  }

  if (!settings) return <div className="settings-page"><section><p>설정을 불러오는 중입니다.</p></section></div>;
  const busy = Boolean(busyAction);
  return <div className="settings-page"><form onSubmit={save} aria-busy={busy}><fieldset className="settings-fields" disabled={busy}>
    <div className="section-heading"><div><h2>Doraemon 설정</h2><p>LLM 연결과 서비스에 공통 적용할 기본 동작을 관리합니다.</p></div>{saved && <span className="saved">저장됨</span>}</div>
    <section className="settings-section"><h3>LLM 연결</h3><div className="settings-form-grid">
      <label>공급자<select value={settings.llm_provider} onChange={(e) => selectProvider(e.target.value as Provider)}><option value="openai">OpenAI · GPT</option><option value="anthropic">Anthropic · Claude</option><option value="gemini">Google · Gemini</option><option value="openrouter">OpenRouter</option><option value="ollama">Ollama · 로컬 모델</option><option value="custom">사용자 지정 API</option></select></label>
      <label>모델<input value={settings.llm_model} onChange={(e) => setSettings({ ...settings, llm_model: e.target.value })} placeholder="모델 ID" /></label>
      {settings.llm_provider !== "openai" && <label className="wide">API 주소<input value={settings.llm_base_url} readOnly={settings.llm_provider !== "custom"} onChange={(e) => setSettings({ ...settings, llm_base_url: e.target.value })} placeholder="공급자 API 주소" /></label>}
      <label className="wide">API 키 <small>{settings.llm_api_key_configured ? "이 공급자의 키가 보관되어 있습니다. 새 값을 입력하면 교체됩니다." : settings.llm_provider === "ollama" ? "로컬 Ollama는 비워둘 수 있습니다." : "선택한 공급자의 API 키를 입력하세요. 다른 공급자의 키는 유지됩니다."}</small><input type="password" autoComplete="new-password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={settings.llm_api_key_configured ? "보관된 키 유지" : "API 키"} /></label>
      <label>최대 출력 토큰<small>코드가 잘리면 늘리고, 모델 한도를 넘으면 줄이세요.</small><input type="number" min="4000" max="128000" step="1000" value={settings.llm_max_output_tokens} onChange={(e) => setSettings({ ...settings, llm_max_output_tokens: Number(e.target.value) })} /></label>
    </div>
      <p className="settings-note">공급자마다 공식 구조화 출력 API를 사용합니다. 연결 확인은 API 키와 모델 조회만 수행하며 유료 생성 요청을 보내지 않습니다.</p>
      {connection && <p className="connection-result success"><strong>연결됨 · {connection.model}</strong><span>{connection.detail}</span></p>}
    </section>
    <section className="settings-section"><h3>기본 동작</h3><div className="settings-form-grid">
      <label>새 서비스 비용 모드<select value={settings.default_cost_mode} onChange={(e) => setSettings({ ...settings, default_cost_mode: e.target.value as Settings["default_cost_mode"] })}><option value="economy">절약</option><option value="balanced">균형</option><option value="quality">품질</option></select></label>
      <label>보관할 버전 수<input type="number" min="1" max="100" value={settings.keep_versions} onChange={(e) => setSettings({ ...settings, keep_versions: Number(e.target.value) })} /></label>
      <label>표시할 로그 줄 수<input type="number" min="50" max="5000" value={settings.log_tail_lines} onChange={(e) => setSettings({ ...settings, log_tail_lines: Number(e.target.value) })} /></label>
      <label>로그 파일 최대 크기(MB)<input type="number" min="1" max="100" value={Math.max(1, Math.round(settings.log_max_bytes / 1_000_000))} onChange={(e) => setSettings({ ...settings, log_max_bytes: Number(e.target.value) * 1_000_000 })} /></label>
      <label>알림 보관 기간(일)<input type="number" min="1" max="3650" value={settings.notification_retention_days} onChange={(e) => setSettings({ ...settings, notification_retention_days: Number(e.target.value) })} /></label>
      <label>알림 최대 개수<input type="number" min="10" max="5000" value={settings.notification_max_items} onChange={(e) => setSettings({ ...settings, notification_max_items: Number(e.target.value) })} /></label>
    </div></section>
    <section className="settings-section"><div className="section-heading"><div><h3>서비스 포트</h3><p>기존 서비스끼리 겹친 포트를 찾아 중지된 서비스에 빈 포트를 배정합니다.</p></div><button type="button" disabled={busy || !ports?.conflicts?.length} onClick={() => void resolvePorts()}>{busyAction === "ports" ? "정리 중…" : "충돌 자동 정리"}</button></div>
      <p className="settings-note">{ports?.conflicts?.length ? `${ports.conflicts.length}개 포트에서 충돌이 발견되었습니다.` : "현재 Doraemon 서비스 간 포트 충돌이 없습니다."}{ports?.changes?.length ? ` 최근 ${ports.changes.length}개 설정을 변경했습니다.` : ""}</p>
      {!!ports?.unresolved_projects?.length && <p className="connection-result">실행 중이라 변경하지 못한 서비스: {ports.unresolved_projects.join(", ")}</p>}
    </section>
    <section className="settings-section"><h3>자동 백업 및 복구</h3><p className="settings-note">설정, 명세, 작업 기록은 변경 전 상태가 자동 보관됩니다. 손상된 원본을 백업에서 복구한 기록은 여기에 표시됩니다.</p>
      {recovery.recovered_count === 0 ? <p>복구가 필요했던 기록이 없습니다.</p> : <div className="finding-list">{recovery.events.slice(-5).reverse().map((event) => <div className="finding info" key={`${event.path}-${event.recovered_at}`}><strong>{event.path}</strong><span>{new Date(event.recovered_at).toLocaleString()}</span></div>)}</div>}
    </section>
    <div className="settings-actions"><button className="primary" type="submit">{busyAction === "save" ? "저장 중…" : "설정 저장"}</button><button type="button" onClick={() => void testConnection()}>{busyAction === "test" ? "확인 중…" : "저장하고 연결 확인"}</button>{settings.llm_api_key_configured && <button type="button" className="danger" onClick={() => void clearKey()}>{busyAction === "clear" ? "삭제 중…" : "이 공급자 키 삭제"}</button>}</div>
  </fieldset></form></div>;
}
