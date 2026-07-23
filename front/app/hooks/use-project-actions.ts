"use client";

import { useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { apiRequest as request } from "../lib/api";
import type { Notification, Project, StudioTab, TrashItem } from "../studio-types";

type Options = {
  selected: Project | null;
  selectedId: string | null;
  setProjects: Dispatch<SetStateAction<Project[]>>;
  setSelectedId: Dispatch<SetStateAction<string | null>>;
  setNotifications: Dispatch<SetStateAction<Notification[]>>;
  setTrashItems: Dispatch<SetStateAction<TrashItem[]>>;
  setNewOpen: Dispatch<SetStateAction<boolean>>;
  setTrashOpen: Dispatch<SetStateAction<boolean>>;
  setTab: Dispatch<SetStateAction<StudioTab>>;
  setError: Dispatch<SetStateAction<string>>;
  refreshProjects: () => Promise<void>;
};

export function useProjectActions(options: Options) {
  const busyRef = useRef("");
  const [busyAction, setBusyAction] = useState("");

  async function runOnce(key: string, fallback: string, action: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = key;
    setBusyAction(key);
    try {
      options.setError("");
      await action();
    } catch (cause) {
      options.setError(cause instanceof Error ? cause.message : fallback);
    } finally {
      busyRef.current = "";
      setBusyAction("");
    }
  }

  async function createProject(name: string, description: string) {
    const project = await request<Project>("/projects", { method: "POST", body: JSON.stringify({ name, description }) });
    await options.refreshProjects(); options.setTab("plan"); options.setSelectedId(project.id); options.setNewOpen(false);
  }

  async function importProject(name: string, description: string, file: File) {
    const body = new FormData();
    body.append("name", name);
    body.append("description", description);
    body.append("file", file);
    const project = await request<Project>("/projects/import", { method: "POST", body });
    await options.refreshProjects();
    options.setTab("runtime");
    options.setSelectedId(project.id);
  }

  async function markNotificationsRead() {
    if (!options.selectedId) return;
    const projectId = options.selectedId;
    await runOnce("read-notifications", "알림을 읽음 처리하지 못했습니다.", async () => {
      await request<void>(`/projects/${projectId}/notifications/read`, { method: "POST" });
      options.setNotifications((items) => items.map((item) => ({ ...item, read: true })));
    });
  }

  async function renameProject() {
    if (!options.selected) return;
    const name = window.prompt("새 서비스 이름", options.selected.name)?.trim();
    if (!name || name === options.selected.name) return;
    const projectId = options.selected.id;
    await runOnce("rename", "서비스 이름을 변경하지 못했습니다.", async () => {
      const updated = await request<Project>(`/projects/${projectId}`, { method: "PATCH", body: JSON.stringify({ name }) });
      options.setProjects((items) => items.map((item) => item.id === updated.id ? updated : item));
    });
  }

  async function cloneProject() {
    if (!options.selected) return;
    const name = window.prompt("복제할 서비스 이름", `${options.selected.name} 복사본`)?.trim();
    if (!name) return;
    const projectId = options.selected.id;
    await runOnce("clone", "서비스를 복제하지 못했습니다.", async () => {
      const cloned = await request<Project>(`/projects/${projectId}/clone`, { method: "POST", body: JSON.stringify({ name }) });
      await options.refreshProjects(); options.setSelectedId(cloned.id); options.setTab("plan");
    });
  }

  async function trashProject() {
    if (!options.selected || !window.confirm(`'${options.selected.name}' 서비스를 휴지통으로 이동할까요?`)) return;
    const projectId = options.selected.id;
    await runOnce("trash", "서비스를 휴지통으로 이동하지 못했습니다.", async () => {
      await request<void>(`/projects/${projectId}`, { method: "DELETE" });
      options.setSelectedId(null); await options.refreshProjects();
    });
  }

  async function openTrash() {
    await runOnce("open-trash", "휴지통을 열지 못했습니다.", async () => {
      options.setTrashItems(await request<TrashItem[]>("/trash")); options.setTrashOpen(true);
    });
  }

  async function restoreTrash(item: TrashItem) {
    await runOnce(`restore-${item.id}`, "서비스를 복구하지 못했습니다.", async () => {
      const restored = await request<Project>(`/trash/${item.id}/restore`, { method: "POST" });
      options.setTrashItems((items) => items.filter((entry) => entry.id !== item.id));
      await options.refreshProjects(); options.setSelectedId(restored.id); options.setTrashOpen(false);
    });
  }

  async function deleteTrash(item: TrashItem) {
    if (!window.confirm(`'${item.name}'을(를) 영구 삭제할까요? 이 작업은 되돌릴 수 없습니다.`)) return;
    await runOnce(`delete-${item.id}`, "영구 삭제하지 못했습니다.", async () => {
      await request<void>(`/trash/${item.id}`, { method: "DELETE" });
      options.setTrashItems((items) => items.filter((entry) => entry.id !== item.id));
    });
  }

  async function openFolder() {
    if (!options.selected) return;
    const projectId = options.selected.id;
    await runOnce("open-folder", "서비스 폴더를 열지 못했습니다.", () =>
      request<void>(`/projects/${projectId}/open-folder`, { method: "POST" }),
    );
  }

  return { busyAction, createProject, importProject, markNotificationsRead, renameProject, cloneProject, trashProject, openTrash, restoreTrash, deleteTrash, openFolder };
}
