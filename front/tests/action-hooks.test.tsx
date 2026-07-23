import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { useImprovementActions } from "../app/hooks/use-improvement-actions";
import { usePlanningActions } from "../app/hooks/use-planning-actions";

const apiRequest = vi.fn();
vi.mock("../app/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../app/lib/api")>(),
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

afterEach(() => vi.clearAllMocks());

function planningOptions(selectedId: string | null) {
  return {
    selectedId,
    setMessages: vi.fn(),
    setPlan: vi.fn(),
    setThinking: vi.fn(),
    setError: vi.fn(),
    setTab: vi.fn(),
    refreshProject: vi.fn(async () => undefined),
    refreshProjects: vi.fn(async () => undefined),
  };
}

function improvementOptions(selectedId: string | null) {
  return {
    selectedId,
    setMessages: vi.fn(),
    setPlan: vi.fn(),
    setThinking: vi.fn(),
    setError: vi.fn(),
    refreshProject: vi.fn(async () => undefined),
  };
}

test("기획 LLM 요청을 연속 호출해도 한 번만 전송한다", () => {
  apiRequest.mockImplementation(() => new Promise(() => undefined));
  const { result, unmount } = renderHook(() => usePlanningActions(planningOptions("project-a")));

  act(() => {
    void result.current.sendMessage("서비스를 기획해줘");
    void result.current.sendMessage("서비스를 기획해줘");
  });

  expect(apiRequest).toHaveBeenCalledTimes(1);
  expect(apiRequest.mock.calls[0][0]).toBe("/projects/project-a/messages");
  unmount();
});

test("개선 LLM 요청을 연속 호출해도 한 번만 전송한다", () => {
  apiRequest.mockImplementation(() => new Promise(() => undefined));
  const { result, unmount } = renderHook(() => useImprovementActions(improvementOptions("project-a")));

  act(() => {
    void result.current.sendImprovement("검색 화면을 개선해줘");
    void result.current.sendImprovement("검색 화면을 개선해줘");
  });

  expect(apiRequest).toHaveBeenCalledTimes(1);
  expect(apiRequest.mock.calls[0][0]).toBe("/projects/project-a/improvements/messages");
  unmount();
});

test("서비스가 바뀌면 진행 중인 기획 요청을 취소한다", () => {
  let signal: AbortSignal | undefined;
  apiRequest.mockImplementation((_path: string, init?: RequestInit) => {
    signal = init?.signal ?? undefined;
    return new Promise(() => undefined);
  });
  const options = planningOptions("project-a");
  const { result, rerender } = renderHook(
    ({ selectedId }) => usePlanningActions({ ...options, selectedId }),
    { initialProps: { selectedId: "project-a" as string | null } },
  );

  act(() => { void result.current.sendMessage("진행 중인 요청"); });
  expect(signal?.aborted).toBe(false);

  rerender({ selectedId: "project-b" });
  expect(signal?.aborted).toBe(true);
});

test("실패한 동일 기획 요청은 같은 요청 ID로 재시도한다", async () => {
  apiRequest
    .mockRejectedValueOnce(new Error("network"))
    .mockResolvedValueOnce({
      assistant_message: { id: "assistant", role: "assistant", content: "응답", created_at: "now" },
      plan: { draft: {} },
    });
  const { result } = renderHook(() => usePlanningActions(planningOptions("project-a")));

  await act(async () => { await result.current.sendMessage("같은 질문"); });
  await act(async () => { await result.current.sendMessage("같은 질문"); });

  const first = JSON.parse(apiRequest.mock.calls[0][1].body);
  const second = JSON.parse(apiRequest.mock.calls[1][1].body);
  expect(first.request_id).toBeTruthy();
  expect(second.request_id).toBe(first.request_id);
});

test("명세 저장을 중복 전송하지 않고 서비스 전환 시 취소한다", () => {
  let signal: AbortSignal | undefined;
  apiRequest.mockImplementation((_path: string, init?: RequestInit) => {
    signal = init?.signal ?? undefined;
    return new Promise(() => undefined);
  });
  const options = planningOptions("project-a");
  const { result, rerender } = renderHook(
    ({ selectedId }) => usePlanningActions({ ...options, selectedId }),
    { initialProps: { selectedId: "project-a" as string | null } },
  );

  act(() => {
    void result.current.saveSpecification("서비스 명세 내용", "기술 명세 내용");
    void result.current.saveSpecification("서비스 명세 내용", "기술 명세 내용");
  });

  expect(apiRequest).toHaveBeenCalledTimes(1);
  expect(apiRequest.mock.calls[0][0]).toBe("/projects/project-a/specification");
  expect(signal?.aborted).toBe(false);

  rerender({ selectedId: "project-b" });
  expect(signal?.aborted).toBe(true);
});
