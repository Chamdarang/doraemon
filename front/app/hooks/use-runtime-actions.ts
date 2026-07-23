"use client";

import { useRef, useState, type Dispatch, type SetStateAction } from "react";
import { apiRequest as request } from "../lib/api";
import type { Job, ProcessState, Project, StudioTab, VersionRecord } from "../studio-types";

type Options = {
  selectedId: string | null;
  setProjects: Dispatch<SetStateAction<Project[]>>;
  setProcesses: Dispatch<SetStateAction<ProcessState[]>>;
  setVersions: Dispatch<SetStateAction<VersionRecord[]>>;
  setThinking: Dispatch<SetStateAction<boolean>>;
  setError: Dispatch<SetStateAction<string>>;
  setRepairDraft: Dispatch<SetStateAction<string>>;
  setTab: Dispatch<SetStateAction<StudioTab>>;
  refreshProject: (id: string) => Promise<void>;
  refreshProjects: () => Promise<void>;
};

export function useRuntimeActions(options: Options) {
  const busyRef = useRef(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  async function runOnce(key: string, action: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusyAction(key);
    try { await action(); }
    finally { busyRef.current = false; setBusyAction(null); }
  }

  async function toggleProcess(target: "backend" | "frontend", running: boolean) {
    if (!options.selectedId) return;
    await runOnce(`process-${target}`, async () => {
      if (!running) options.setProcesses((items) => items.map((item) => item.target === target ? { ...item, phase: "starting", message: "의존성과 실행 환경을 준비하고 있습니다" } : item));
      try {
        const next = await request<ProcessState>(`/projects/${options.selectedId}/processes/${target}/${running ? "stop" : "start"}`, { method: "POST" });
        options.setProcesses((items) => items.map((item) => item.target === target ? next : item));
      } catch (cause) {
        const message = cause instanceof Error ? cause.message : "실행 상태를 변경하지 못했습니다.";
        options.setProcesses((items) => items.map((item) => item.target === target ? { ...item, running: false, pid: null, phase: "error", message } : item));
        options.setError(message);
      }
    });
  }

  async function toggleAll(action: "start" | "stop") {
    if (!options.selectedId) return;
    await runOnce(`process-${action}-all`, async () => {
    if (action === "start") {
      options.setProcesses((items) => items.map((item) => item.running ? item : {
        ...item,
        phase: "starting",
        message: "전체 실행을 준비하고 있습니다",
      }));
    }
    try {
      const next = await request<ProcessState[]>(`/projects/${options.selectedId}/processes/${action}-all`, { method: "POST" });
      options.setProcesses(next);
      options.setError("");
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : `전체 ${action === "start" ? "실행" : "중지"}에 실패했습니다`;
      try {
        const current = await request<ProcessState[]>(`/projects/${options.selectedId}/processes`);
        options.setProcesses(current);
      } catch {
        // Preserve the last known state when the status refresh also fails.
      }
      options.setError(message);
    }
    });
  }

  async function savePorts(backendPort: number, frontendPort: number) {
    if (!options.selectedId) return;
    await runOnce("ports", async () => { try {
      const updated = await request<Project>(`/projects/${options.selectedId}/runtime/ports`, { method: "PUT", body: JSON.stringify({ backend_port: backendPort, frontend_port: frontendPort }) });
      options.setProjects((items) => items.map((item) => item.id === updated.id ? updated : item));
      options.setProcesses((items) => items.map((item) => ({ ...item, port: item.target === "backend" ? backendPort : frontendPort })));
      options.setError("");
    } catch (cause) { options.setError(cause instanceof Error ? cause.message : "포트를 저장하지 못했습니다."); } });
  }

  async function cancelJob(jobId: string) {
    if (!options.selectedId) return;
    const projectId = options.selectedId;
    await runOnce(`cancel-${jobId}`, async () => {
      try {
        await request<Job>(`/projects/${projectId}/jobs/${jobId}/cancel`, { method: "POST" });
        await options.refreshProject(projectId); await options.refreshProjects();
      } catch (cause) { options.setError(cause instanceof Error ? cause.message : "작업을 취소하지 못했습니다."); }
    });
  }

  async function resumeJob(jobId: string) {
    if (!options.selectedId) return;
    const projectId = options.selectedId;
    await runOnce(`resume-${jobId}`, async () => { try {
      await request<Job>(`/projects/${projectId}/jobs/${jobId}/resume`, { method: "POST" });
      await options.refreshProject(projectId); await options.refreshProjects();
    } catch (cause) { options.setError(cause instanceof Error ? cause.message : "작업을 다시 시작하지 못했습니다."); } });
  }

  async function clearCache() {
    if (!options.selectedId) return;
    await runOnce("cache", async () => {
      try {
        await request<void>(`/projects/${options.selectedId}/cache`, { method: "DELETE" });
        options.setError("");
      } catch (cause) { options.setError(cause instanceof Error ? cause.message : "생성 캐시를 비우지 못했습니다."); }
    });
  }

  async function startRepair(content: string) {
    if (!options.selectedId) return;
    const projectId = options.selectedId;
    await runOnce("repair", async () => {
    options.setThinking(true); options.setError("");
    try {
      await request<Job>(`/projects/${projectId}/repairs`, { method: "POST", body: JSON.stringify({ content }) });
      options.setRepairDraft("");
      await options.refreshProject(projectId);
    } catch (cause) { options.setError(cause instanceof Error ? cause.message : "오류 수정을 시작하지 못했습니다."); }
    finally { options.setThinking(false); }
    });
  }

  function openRepairFromRuntime(draft: string) { options.setRepairDraft(draft); options.setTab("repair"); }

  async function restoreVersion(versionId: string) {
    if (!options.selectedId) return;
    const projectId = options.selectedId;
    await runOnce(`restore-${versionId}`, async () => { try {
      await request<VersionRecord>(`/projects/${projectId}/versions/${versionId}/restore`, { method: "POST" });
      await options.refreshProject(projectId); await options.refreshProjects();
    } catch (cause) { options.setError(cause instanceof Error ? cause.message : "버전을 복원하지 못했습니다."); } });
  }

  async function deleteVersion(versionId: string) {
    if (!options.selectedId || !window.confirm("이 복원 버전을 삭제할까요? 현재 실행 파일은 삭제되지 않습니다.")) return;
    await runOnce(`delete-${versionId}`, async () => { try {
      await request<void>(`/projects/${options.selectedId}/versions/${versionId}`, { method: "DELETE" });
      options.setVersions((items) => items.filter((item) => item.id !== versionId));
    } catch (cause) { options.setError(cause instanceof Error ? cause.message : "버전을 삭제하지 못했습니다."); } });
  }

  async function setCostMode(mode: "economy" | "balanced" | "quality") {
    if (!options.selectedId) return;
    await runOnce("cost-mode", async () => {
      try {
        const limits = mode === "economy" ? [25_000, 45_000] : mode === "quality" ? [70_000, 120_000] : [40_000, 70_000];
        const updated = await request<Project>(`/projects/${options.selectedId}`, { method: "PATCH", body: JSON.stringify({ llm_policy: { mode, planning_source_limit: limits[0], generation_source_limit: limits[1] } }) });
        options.setProjects((items) => items.map((item) => item.id === updated.id ? updated : item));
      } catch (cause) { options.setError(cause instanceof Error ? cause.message : "비용 모드를 변경하지 못했습니다."); }
    });
  }

  return { toggleProcess, toggleAll, savePorts, cancelJob, resumeJob, clearCache, startRepair, openRepairFromRuntime, restoreVersion, deleteVersion, setCostMode, busyAction };
}
