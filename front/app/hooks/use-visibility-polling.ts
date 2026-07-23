"use client";

import { useEffect, useRef } from "react";

type PollingOptions = {
  enabled?: boolean;
  baseDelay: number;
  maxDelay?: number;
};

export function useVisibilityPolling(task: (signal: AbortSignal) => Promise<unknown>, {
  enabled = true,
  baseDelay,
  maxDelay = 30_000,
}: PollingOptions) {
  const taskRef = useRef(task);
  useEffect(() => { taskRef.current = task; }, [task]);

  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let timer: number | undefined;
    let controller: AbortController | undefined;
    let delay = baseDelay;

    const schedule = (wait: number) => {
      if (!stopped && !document.hidden) timer = window.setTimeout(tick, wait);
    };
    const tick = async () => {
      if (stopped || document.hidden) return;
      controller = new AbortController();
      try {
        await taskRef.current(controller.signal);
        delay = baseDelay;
      } catch {
        if (controller.signal.aborted) return;
        delay = Math.min(maxDelay, delay * 2);
      }
      controller = undefined;
      schedule(delay);
    };
    const visibilityChanged = () => {
      if (timer !== undefined) window.clearTimeout(timer);
      controller?.abort();
      if (!document.hidden) {
        delay = baseDelay;
        schedule(0);
      }
    };

    document.addEventListener("visibilitychange", visibilityChanged);
    schedule(0);
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, [baseDelay, enabled, maxDelay]);
}
