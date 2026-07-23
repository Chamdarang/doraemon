"use client";

import { useCallback, useState } from "react";
import { ApiError, apiRequest, isAbortError } from "../lib/api";
import type { LlmActivity } from "../studio-types";
import { useVisibilityPolling } from "./use-visibility-polling";

const idle: LlmActivity = { busy: false, project_id: null, operation: null, estimated_input_tokens: 0, started_at: null };

export function useLlmActivity() {
  const [activity, setActivity] = useState<LlmActivity>(idle);
  const [connection, setConnection] = useState<"checking" | "online" | "offline">("checking");
  const refresh = useCallback(async (signal: AbortSignal) => {
    try {
      setActivity(await apiRequest<LlmActivity>("/settings/llm/activity", { signal }));
      setConnection("online");
    } catch (cause) {
      if (!isAbortError(cause)) setConnection(cause instanceof ApiError ? "online" : "offline");
      throw cause;
    }
  }, []);
  useVisibilityPolling(refresh, { baseDelay: activity.busy ? 1200 : 3000 });
  return { activity, connection };
}
