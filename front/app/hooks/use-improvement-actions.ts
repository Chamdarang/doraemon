"use client";

import { useEffect, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";
import { apiRequest as request, isAbortError } from "../lib/api";
import type { ImprovementExchange, ImprovementPlan, Job, Message } from "../studio-types";

type Options = {
  selectedId: string | null;
  setMessages: Dispatch<SetStateAction<Message[]>>;
  setPlan: Dispatch<SetStateAction<ImprovementPlan | null>>;
  setThinking: Dispatch<SetStateAction<boolean>>;
  setError: Dispatch<SetStateAction<string>>;
  refreshProject: (id: string) => Promise<void>;
};

export function useImprovementActions(options: Options) {
  const operationRef = useRef<AbortController | null>(null);
  const retryRequestRef = useRef<{ key: string; id: string } | null>(null);
  const selectedId = options.selectedId;
  const setThinking = options.setThinking;

  useEffect(() => {
    return () => {
      operationRef.current?.abort();
      operationRef.current = null;
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

  async function sendImprovement(content: string) {
    if (!options.selectedId) return;
    const controller = beginOperation();
    if (!controller) return;
    const projectId = options.selectedId;
    const retryKey = JSON.stringify([projectId, content]);
    const requestId = retryRequestRef.current?.key === retryKey
      ? retryRequestRef.current.id
      : globalThis.crypto?.randomUUID?.() ?? `req-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    retryRequestRef.current = { key: retryKey, id: requestId };
    const optimistic: Message = { id: `local-improvement-${Date.now()}`, role: "user", content, created_at: new Date().toISOString() };
    options.setMessages((current) => [...current, optimistic]);
    try {
      const exchange = await request<ImprovementExchange>(`/projects/${projectId}/improvements/messages`, {
        method: "POST",
        body: JSON.stringify({ content, request_id: requestId }),
        signal: controller.signal,
      });
      options.setMessages((current) => [...current.filter((item) => item.id !== optimistic.id), optimistic, exchange.assistant_message]);
      options.setPlan(exchange.plan);
      retryRequestRef.current = null;
      if (exchange.plan.draft.changes.length && exchange.plan.draft.acceptance_criteria.length && !exchange.plan.draft.open_questions.length) {
        try {
          await request<ImprovementPlan>(`/projects/${projectId}/improvement/approve`, { method: "POST", signal: controller.signal });
          await request<Job>(`/projects/${projectId}/improvement/apply`, { method: "POST", signal: controller.signal });
          await options.refreshProject(projectId);
        } catch (cause) {
          if (!isAbortError(cause)) options.setError(cause instanceof Error ? cause.message : "자동 적용을 시작하지 못했습니다.");
        }
      }
    } catch (cause) {
      options.setMessages((current) => current.filter((item) => item.id !== optimistic.id));
      if (!isAbortError(cause)) options.setError(cause instanceof Error ? cause.message : "개선 요청을 보내지 못했습니다.");
    } finally {
      finishOperation(controller);
    }
  }

  async function applyImprovement() {
    if (!options.selectedId) return;
    const controller = beginOperation();
    if (!controller) return;
    const projectId = options.selectedId;
    try {
      options.setPlan(await request<ImprovementPlan>(`/projects/${projectId}/improvement/approve`, { method: "POST", signal: controller.signal }));
      await request<Job>(`/projects/${projectId}/improvement/apply`, { method: "POST", signal: controller.signal });
      await options.refreshProject(projectId);
    } catch (cause) {
      if (!isAbortError(cause)) options.setError(cause instanceof Error ? cause.message : "개선을 시작하지 못했습니다.");
    } finally {
      finishOperation(controller);
    }
  }

  return { sendImprovement, applyImprovement };
}
