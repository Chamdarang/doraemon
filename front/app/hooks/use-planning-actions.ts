"use client";

import { useEffect, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";
import { apiRequest as request, isAbortError } from "../lib/api";
import type { Exchange, Job, Message, Plan, StudioTab } from "../studio-types";

type Options = {
  selectedId: string | null;
  setMessages: Dispatch<SetStateAction<Message[]>>;
  setPlan: Dispatch<SetStateAction<Plan | null>>;
  setThinking: Dispatch<SetStateAction<boolean>>;
  setError: Dispatch<SetStateAction<string>>;
  setTab: Dispatch<SetStateAction<StudioTab>>;
  refreshProject: (id: string) => Promise<void>;
  refreshProjects: () => Promise<void>;
};

export function usePlanningActions(options: Options) {
  const operationRef = useRef<AbortController | null>(null);
  const specificationRef = useRef<AbortController | null>(null);
  const retryRequestRef = useRef<{ key: string; id: string } | null>(null);
  const selectedId = options.selectedId;
  const setThinking = options.setThinking;

  useEffect(() => {
    return () => {
      operationRef.current?.abort();
      operationRef.current = null;
      specificationRef.current?.abort();
      specificationRef.current = null;
      setThinking(false);
    };
  }, [selectedId, setThinking]);

  function beginOperation() {
    if (operationRef.current) return null;
    const controller = new AbortController();
    operationRef.current = controller;
    setThinking(true);
    options.setError("");
    return controller;
  }

  function finishOperation(controller: AbortController) {
    if (operationRef.current !== controller) return;
    operationRef.current = null;
    setThinking(false);
  }

  async function sendMessage(content: string, applyRecommendations = false) {
    if (!options.selectedId) return;
    const controller = beginOperation();
    if (!controller) return;
    const projectId = options.selectedId;
    const retryKey = JSON.stringify([projectId, content, applyRecommendations]);
    const requestId = retryRequestRef.current?.key === retryKey
      ? retryRequestRef.current.id
      : globalThis.crypto?.randomUUID?.() ?? `req-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    retryRequestRef.current = { key: retryKey, id: requestId };
    const optimistic: Message = { id: `local-${Date.now()}`, role: "user", content, created_at: new Date().toISOString() };
    options.setMessages((current) => [...current, optimistic]);
    try {
      const exchange = await request<Exchange>(`/projects/${projectId}/messages`, {
        method: "POST",
        body: JSON.stringify({ content, apply_recommendations: applyRecommendations, request_id: requestId }),
        signal: controller.signal,
      });
      options.setMessages((current) => [...current.filter((item) => item.id !== optimistic.id), optimistic, exchange.assistant_message]);
      options.setPlan(exchange.plan);
      retryRequestRef.current = null;
    } catch (cause) {
      options.setMessages((current) => current.filter((item) => item.id !== optimistic.id));
      if (!isAbortError(cause)) options.setError(cause instanceof Error ? cause.message : "메시지를 보내지 못했습니다.");
    } finally {
      finishOperation(controller);
    }
  }

  async function approveAndGenerate() {
    if (!options.selectedId) return;
    const controller = beginOperation();
    if (!controller) return;
    const projectId = options.selectedId;
    try {
      const approved = await request<Plan>(`/projects/${projectId}/plan/approve`, { method: "POST", signal: controller.signal });
      options.setPlan(approved);
      await request<Job>(`/projects/${projectId}/generate`, { method: "POST", signal: controller.signal });
      options.setTab("runtime");
      await options.refreshProject(projectId);
      await options.refreshProjects();
    } catch (cause) {
      if (!isAbortError(cause)) options.setError(cause instanceof Error ? cause.message : "생성을 시작하지 못했습니다.");
    } finally {
      finishOperation(controller);
    }
  }

  async function saveSpecification(serviceSpecification: string, technicalSpecification: string) {
    if (!options.selectedId) return;
    if (specificationRef.current) return;
    const controller = new AbortController();
    specificationRef.current = controller;
    const projectId = options.selectedId;
    options.setError("");
    try {
      const updated = await request<Plan>(`/projects/${projectId}/specification`, {
        method: "PUT",
        body: JSON.stringify({ service_specification: serviceSpecification, technical_specification: technicalSpecification }),
        signal: controller.signal,
      });
      if (specificationRef.current === controller) options.setPlan(updated);
    } catch (cause) {
      if (!isAbortError(cause)) options.setError(cause instanceof Error ? cause.message : "명세를 저장하지 못했습니다.");
    } finally {
      if (specificationRef.current === controller) specificationRef.current = null;
    }
  }

  return { sendMessage, approveAndGenerate, saveSpecification };
}
