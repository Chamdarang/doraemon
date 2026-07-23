"use client";

import { Dispatch, SetStateAction, useCallback, useEffect, useRef, useState } from "react";
import { apiRequest as request, isAbortError } from "../lib/api";
import { useVisibilityPolling } from "./use-visibility-polling";
import type { ImprovementPlan, Job, Message, Notification, Plan, ProcessState, Project, ProjectOverview, ProjectWorkspace, RuntimeSnapshot, UsageSummary, VersionRecord } from "../studio-types";

export function useProjectWorkspace(setError: Dispatch<SetStateAction<string>>) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [improvementMessages, setImprovementMessages] = useState<Message[]>([]);
  const [improvementPlan, setImprovementPlan] = useState<ImprovementPlan | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [processes, setProcesses] = useState<ProcessState[]>([]);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [versions, setVersions] = useState<VersionRecord[]>([]);
  const [repairMessages, setRepairMessages] = useState<Message[]>([]);
  const [overviewById, setOverviewById] = useState<Record<string, ProjectOverview>>({});
  const [selectedOverview, setSelectedOverview] = useState<ProjectOverview | null>(null);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const refreshVersion = useRef(0);
  const activityPolling = useRef(false);
  const projectListError = useRef("");
  const selectedIdRef = useRef<string | null>(null);
  const selected = projects.find((project) => project.id === selectedId) ?? null;

  useEffect(() => { selectedIdRef.current = selectedId; }, [selectedId]);

  const refreshProjects = useCallback(async (signal?: AbortSignal) => {
    try {
      const [data, overviewResponse] = await Promise.all([
        request<Project[]>("/projects", { signal }),
        request<ProjectOverview[]>("/projects/overviews", { signal }).catch((cause) => {
          if (isAbortError(cause)) throw cause;
          return [];
        }),
      ]);
      const overviews = Array.isArray(overviewResponse) ? overviewResponse : [];
      setProjects(data);
      setOverviewById(Object.fromEntries(overviews.map((item) => [item.project_id, item])));
      setSelectedId((current) => current ?? data[0]?.id ?? null);
      if (projectListError.current) {
        const resolved = projectListError.current;
        projectListError.current = "";
        setError((current) => current === resolved ? "" : current);
      }
    } catch (cause) {
      if (isAbortError(cause)) return;
      const message = cause instanceof Error ? cause.message : "백엔드에 연결할 수 없습니다.";
      projectListError.current = message;
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [setError]);

  const refreshProject = useCallback(async (projectId: string, signal?: AbortSignal) => {
    const version = ++refreshVersion.current;
    const workspace = await request<ProjectWorkspace>(`/projects/${projectId}/workspace`, { signal });
    if (version !== refreshVersion.current || selectedIdRef.current !== projectId) return;
    setMessages(workspace.messages);
    setJobs(workspace.jobs);
    setProcesses(workspace.processes);
    setImprovementMessages(workspace.improvement_messages);
    setPlan(workspace.plan);
    setImprovementPlan(workspace.improvement_plan);
    setUsage(workspace.usage);
    setVersions(workspace.versions);
    setRepairMessages(workspace.repair_messages);
    setSelectedOverview(workspace.overview);
    setNotifications(workspace.notifications);
  }, []);

  const refreshActivity = useCallback(async (projectId: string, signal?: AbortSignal) => {
    if (activityPolling.current) return;
    activityPolling.current = true;
    try {
      const snapshot = await request<RuntimeSnapshot>(`/projects/${projectId}/runtime-snapshot?include_logs=false`, { signal });
      if (selectedIdRef.current !== projectId) return;
      setJobs(snapshot.jobs);
      setProcesses(snapshot.processes);
      setSelectedOverview(snapshot.overview);
      setOverviewById((current) => ({ ...current, [projectId]: snapshot.overview }));
      setNotifications(snapshot.notifications);
      if (!snapshot.jobs.some((job) => !["completed", "failed", "cancelled"].includes(job.status))) {
        await Promise.all([refreshProject(projectId), refreshProjects()]);
      }
    } finally {
      activityPolling.current = false;
    }
  }, [refreshProject, refreshProjects]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void refreshProjects(controller.signal), 0);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [refreshProjects]);
  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    void refreshProject(selectedId, controller.signal).catch((cause) => {
      if (!isAbortError(cause)) setError(String(cause));
    });
    return () => controller.abort();
  }, [selectedId, refreshProject, setError]);
  const hasActiveJob = jobs.some((job) => !["completed", "failed", "cancelled"].includes(job.status));
  useVisibilityPolling(async (signal) => {
    if (!selectedId) return;
    try { await refreshActivity(selectedId, signal); }
    catch (cause) { setError(String(cause)); throw cause; }
  }, { enabled: Boolean(selectedId && hasActiveJob), baseDelay: 1800 });

  return {
    projects, setProjects, selectedId, setSelectedId, selected, messages, setMessages, plan, setPlan,
    improvementMessages, setImprovementMessages, improvementPlan, setImprovementPlan, jobs, processes, setProcesses,
    usage, versions, setVersions, repairMessages, overviewById, selectedOverview, notifications,
    setNotifications, loading, refreshProjects, refreshProject,
  };
}
