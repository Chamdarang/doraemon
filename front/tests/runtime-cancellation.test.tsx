import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { RuntimeView } from "../app/features/runtime-view";
import type { ProcessState } from "../app/studio-types";

const apiRequest = vi.fn();
vi.mock("../app/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../app/lib/api")>(),
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

test("실행 탭을 닫으면 진행 중인 버전 비교 요청을 취소한다", async () => {
  const states: ProcessState[] = [
    { target: "backend", running: false, pid: null, port: 8001, phase: "stopped", message: null, command: [] },
    { target: "frontend", running: false, pid: null, port: 5174, phase: "stopped", message: null, command: [] },
  ];
  let diffSignal: AbortSignal | undefined;
  apiRequest.mockImplementation((path: string, init?: RequestInit) => {
    if (path.endsWith("/versions/version-1/diff")) {
      diffSignal = init?.signal ?? undefined;
      return new Promise(() => undefined);
    }
    if (path.includes("/runtime-snapshot")) return Promise.resolve({ processes: states, logs: { backend: { logs: "", cursor: 0, log_id: "", reset: true }, frontend: { logs: "", cursor: 0, log_id: "", reset: true } } });
    if (path.endsWith("/technology-stack")) return Promise.resolve({ backend: [], frontend: [], infrastructure: [] });
    if (path.endsWith("/infrastructure")) return Promise.resolve({ docker_available: false, services: [], port_settings: [], message: "", errors: [] });
    return Promise.resolve({ disk_bytes: 0, logs_bytes: 0, cache_bytes: 0, versions_bytes: 0, version_count: 1 });
  });
  const { container, unmount } = render(<RuntimeView projectId="demo" states={states} jobs={[]} usage={null} versions={[{ id: "version-1", label: "첫 생성", source_job_id: null, created_at: new Date().toISOString() }]} overview={null} costMode="balanced" onStates={vi.fn()} onToggle={vi.fn()} onToggleAll={vi.fn()} onPorts={vi.fn()} onCancel={vi.fn()} onResume={vi.fn()} onClearCache={vi.fn()} onRestore={vi.fn()} onDeleteVersion={vi.fn()} onCostMode={vi.fn()} onOpenRepair={vi.fn()} />);

  const compare = container.querySelector<HTMLButtonElement>(".version-manager .version-entry button");
  if (!compare) throw new Error("version compare button not found");
  fireEvent.click(compare);
  await waitFor(() => expect(diffSignal).toBeTruthy());
  expect(diffSignal?.aborted).toBe(false);

  unmount();
  expect(diffSignal?.aborted).toBe(true);
});
