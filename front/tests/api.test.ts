import { afterEach, expect, test, vi } from "vitest";

import { ApiError, apiRequest, isAbortError } from "../app/lib/api";

afterEach(() => vi.unstubAllGlobals());

test("API 검증 오류의 핵심 메시지와 상태 코드를 보존한다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    detail: [{ msg: "포트가 이미 사용 중입니다" }, { msg: "다른 포트를 선택하세요" }],
  }), { status: 422, headers: { "Content-Type": "application/json" } })));

  const error = await apiRequest("/projects/demo").catch((cause) => cause);

  expect(error).toBeInstanceOf(ApiError);
  if (!(error instanceof ApiError)) throw new Error("ApiError가 반환되지 않았습니다");
  expect(error.status).toBe(422);
  expect(error.message).toBe("포트가 이미 사용 중입니다 · 다른 포트를 선택하세요");
});

test("화면에서 취소한 요청은 연결 오류로 바꾸지 않는다", async () => {
  vi.stubGlobal("fetch", vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
    init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
  })));
  const controller = new AbortController();
  const pending = apiRequest("/projects/demo/workspace", { signal: controller.signal });

  controller.abort();

  const error = await pending.catch((cause) => cause);
  expect(isAbortError(error)).toBe(true);
});
