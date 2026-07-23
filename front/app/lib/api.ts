export const API = process.env.NEXT_PUBLIC_POCKET_API_URL ?? "http://localhost:8000/api";

export type ApiRequestInit = RequestInit & { timeoutMs?: number };

export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly detail?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

export function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}

export function apiUrl(path: string) {
  return `${API}${path}`;
}

export async function apiRequest<T>(path: string, init: ApiRequestInit = {}): Promise<T> {
  const { timeoutMs = 180_000, signal: externalSignal, ...requestInit } = init;
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort(externalSignal?.reason);
  if (externalSignal?.aborted) abort();
  else externalSignal?.addEventListener("abort", abort, { once: true });
  const timer = timeoutMs > 0 ? window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs) : undefined;
  let response: Response;
  try {
    const isFormData = typeof FormData !== "undefined" && requestInit.body instanceof FormData;
    const headers = new Headers(requestInit.headers);
    if (!isFormData && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    response = await fetch(`${API}${path}`, {
      ...requestInit,
      headers,
      signal: controller.signal,
    });
  } catch (error) {
    if (timedOut) throw new Error("요청 시간이 초과되었습니다. 서버 상태를 확인한 뒤 다시 시도해주세요.");
    if (isAbortError(error) || externalSignal?.aborted) throw error;
    throw new Error("Doraemon API에 연결할 수 없습니다. 프로젝트 폴더의 start.cmd를 실행해주세요.");
  } finally {
    if (timer !== undefined) window.clearTimeout(timer);
    externalSignal?.removeEventListener("abort", abort);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null;
    const detail = body?.detail;
    const message = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map((item) => typeof item === "object" && item && "msg" in item ? String(item.msg) : String(item)).join(" · ")
        : `요청에 실패했습니다 (${response.status})`;
    throw new ApiError(message, response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
