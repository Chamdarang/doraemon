import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { useVisibilityPolling } from "../app/hooks/use-visibility-polling";

function PollingProbe({ task }: { task: () => Promise<unknown> }) {
  useVisibilityPolling(task, { baseDelay: 100, maxDelay: 800 });
  return null;
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
});

test("숨겨진 탭에서는 중단되고 실패하면 지수형 간격으로 재시도한다", async () => {
  vi.useFakeTimers();
  Object.defineProperty(document, "hidden", { configurable: true, value: true });
  const task = vi.fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue(undefined);
  render(<PollingProbe task={task} />);

  await vi.advanceTimersByTimeAsync(2_000);
  expect(task).not.toHaveBeenCalled();

  Object.defineProperty(document, "hidden", { configurable: true, value: false });
  document.dispatchEvent(new Event("visibilitychange"));
  await vi.advanceTimersByTimeAsync(0);
  expect(task).toHaveBeenCalledTimes(1);

  await vi.advanceTimersByTimeAsync(199);
  expect(task).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(task).toHaveBeenCalledTimes(2);

  await vi.advanceTimersByTimeAsync(399);
  expect(task).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(1);
  expect(task).toHaveBeenCalledTimes(3);
});
