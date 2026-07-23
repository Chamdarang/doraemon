import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { EnvironmentView } from "../app/features/environment-view";
import { ImprovementView } from "../app/features/improvement-view";
import { PlanningView } from "../app/features/planning-view";
import { RepairView } from "../app/features/repair-view";
import { RuntimeView } from "../app/features/runtime-view";
import { SettingsView } from "../app/features/settings-view";
import { CreateServiceDialog, ImportServiceDialog } from "../app/features/studio-dialogs";
import { StudioHeader, StudioSidebar } from "../app/features/studio-shell";
import { ToolsView } from "../app/features/tools-view";
import type { ImprovementPlan, Job, Plan, ProcessState, Project } from "../app/studio-types";

const apiRequest = vi.fn();
vi.mock("../app/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../app/lib/api")>(),
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

Object.defineProperty(Element.prototype, "scrollIntoView", {
  configurable: true,
  value: vi.fn(),
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const implementation = {
  architecture: "단일 로컬 서비스",
  technology_choices: [],
  components: ["API", "Web"],
  directories: [{ path: "back/", purpose: "API" }, { path: "front/", purpose: "Web" }],
  data_and_state: "로컬 상태",
  api_and_integrations: "HTTP API",
  runtime_and_configuration: "로컬 실행",
  testing_strategy: "수동 실행 확인",
};

function planningPlan(complete: boolean): Plan {
  return {
    draft: {
      reply: "명세를 정리했습니다.",
      stage: "review",
      decisions: complete ? ["architecture", "components", "frontend_stack", "backend_stack", "persistence", "repository_layout", "runtime_infrastructure", "testing"].map((category) => ({ category, choice: "확정", rationale: "사용자 선택", confirmed: true })) : [],
      open_questions: [],
      implementation_plan: complete ? implementation : null,
      ready_to_generate: complete,
      specification: complete ? "완성된 명세" : null,
      service_specification: complete ? "충분히 구체적인 서비스 명세입니다." : null,
      technical_specification: complete ? "충분히 구체적인 기술 명세입니다." : null,
    },
    approved: false,
    updated_at: "2026-07-14T00:00:00Z",
  };
}

function improvementPlan(openQuestions: string[] = []): ImprovementPlan {
  return {
    draft: {
      reply: "변경안을 정리했습니다.",
      goal: "화면 개선",
      analysis: "현재 화면을 개선합니다.",
      changes: [{ path: "front/app.tsx", action: "modify", reason: "사용성 개선" }],
      acceptance_criteria: ["화면이 정상적으로 표시됨"],
      open_questions: openQuestions,
      ready_to_apply: openQuestions.length === 0,
    },
    approved: false,
    applied_at: null,
    updated_at: "2026-07-14T00:00:00Z",
  };
}

test("기획 입력은 Enter로 전송되고 완성된 명세만 생성할 수 있다", async () => {
  const onSend = vi.fn(async () => undefined);
  const onGenerate = vi.fn(async () => undefined);
  const { rerender } = render(<PlanningView messages={[]} plan={planningPlan(false)} thinking={false} jobs={[]} onSend={onSend} onGenerate={onGenerate} onOpenRepair={vi.fn()} onSaveSpecification={vi.fn()} />);

  const generate = screen.getByRole("button", { name: /현재 명세 승인하고 생성/ });
  expect((generate as HTMLButtonElement).disabled).toBe(true);
  const composer = screen.getByPlaceholderText("답변하거나 새로운 요구사항을 입력하세요");
  fireEvent.change(composer, { target: { value: "React로 만들어줘" } });
  fireEvent.keyDown(composer, { key: "Enter" });
  await waitFor(() => expect(onSend).toHaveBeenCalledWith("React로 만들어줘"));

  rerender(<PlanningView messages={[]} plan={planningPlan(true)} thinking={false} jobs={[]} onSend={onSend} onGenerate={onGenerate} onOpenRepair={vi.fn()} onSaveSpecification={vi.fn()} />);
  const enabled = screen.getByRole("button", { name: /현재 명세 승인하고 생성/ });
  expect((enabled as HTMLButtonElement).disabled).toBe(false);
  await userEvent.click(enabled);
  expect(onGenerate).toHaveBeenCalledOnce();
});

test("개선안은 남은 질문이 없을 때 추가 대화 없이 적용할 수 있다", async () => {
  const onApply = vi.fn(async () => undefined);
  const { rerender } = render(<ImprovementView messages={[]} plan={improvementPlan(["색상을 결정해야 합니다."])} thinking={false} jobs={[]} onSend={vi.fn()} onApply={onApply} />);
  expect((screen.getByRole("button", { name: /변경사항 승인하고 적용/ }) as HTMLButtonElement).disabled).toBe(true);

  rerender(<ImprovementView messages={[]} plan={improvementPlan()} thinking={false} jobs={[]} onSend={vi.fn()} onApply={onApply} />);
  const apply = screen.getByRole("button", { name: /변경사항 승인하고 적용/ });
  expect((apply as HTMLButtonElement).disabled).toBe(false);
  await userEvent.click(apply);
  expect(onApply).toHaveBeenCalledOnce();
});

test("실행 화면은 준비 완료 전 시작 버튼을 잠그고 실행 상태만 가볍게 갱신한다", async () => {
  const states: ProcessState[] = [
    { target: "backend", running: false, pid: null, port: 8001, phase: "starting", message: "준비 중", command: ["python", "-m", "uvicorn"] },
    { target: "frontend", running: true, pid: 42, port: 5174, phase: "ready", message: null, command: ["npm", "run", "dev"] },
  ];
  apiRequest.mockImplementation(async (path: string) => {
    if (path.includes("/runtime-snapshot")) return {
      processes: states,
      jobs: [],
      overview: { project_id: "demo", backend_running: false, frontend_running: true, missing_environment: [], health: [] },
      notifications: [],
      logs: {
        backend: { logs: "", cursor: 0, log_id: "", reset: true },
        frontend: { logs: "", cursor: 0, log_id: "", reset: true },
      },
    };
    if (path.endsWith("/processes")) return states;
    if (path.includes("/logs/chunk")) return { logs: "", cursor: 0, log_id: "", reset: true };
    if (path.endsWith("/technology-stack")) return { backend: [], frontend: [], infrastructure: [] };
    return { disk_bytes: 0, logs_bytes: 0, cache_bytes: 0, versions_bytes: 0, version_count: 0 };
  });
  const onStates = vi.fn();
  render(<RuntimeView projectId="demo" states={states} jobs={[]} usage={null} versions={[]} overview={null} costMode="balanced" onStates={onStates} onToggle={vi.fn()} onToggleAll={vi.fn()} onPorts={vi.fn()} onCancel={vi.fn()} onResume={vi.fn()} onClearCache={vi.fn()} onRestore={vi.fn()} onDeleteVersion={vi.fn()} onCostMode={vi.fn()} onOpenRepair={vi.fn()} />);

  expect((screen.getByRole("button", { name: "준비 중" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByTitle("생성 서비스 미리보기")).toBeTruthy();
  expect(screen.getByText("준비 완료 · PID 42")).toBeTruthy();
  await waitFor(() => expect(onStates).toHaveBeenCalledWith(states));
  expect(apiRequest.mock.calls.some(([path]) => String(path).includes("/projects/demo/runtime-snapshot"))).toBe(true);
  expect(apiRequest).not.toHaveBeenCalledWith("/projects/demo/processes");
});

test("전체 실행과 전체 중지 버튼은 통합 런타임 액션을 호출한다", async () => {
  const stopped: ProcessState[] = [
    { target: "backend", running: false, pid: null, port: 8001, phase: "stopped", message: null, command: ["run"] },
    { target: "frontend", running: false, pid: null, port: 5174, phase: "stopped", message: null, command: ["run"] },
  ];
  apiRequest.mockImplementation(async (path: string) => {
    if (path.endsWith("/processes")) return stopped;
    if (path.includes("/logs/chunk")) return { logs: "", cursor: 0, log_id: "", reset: true };
    if (path.endsWith("/technology-stack")) return { backend: [], frontend: [], infrastructure: [] };
    return { disk_bytes: 0, logs_bytes: 0, cache_bytes: 0, versions_bytes: 0, version_count: 0 };
  });
  const onToggleAll = vi.fn(async () => undefined);
  const baseProps = { projectId: "demo", jobs: [], usage: null, versions: [], overview: null, costMode: "balanced" as const, onStates: vi.fn(), onToggle: vi.fn(), onToggleAll, onPorts: vi.fn(), onCancel: vi.fn(), onResume: vi.fn(), onClearCache: vi.fn(), onRestore: vi.fn(), onDeleteVersion: vi.fn(), onCostMode: vi.fn(), onOpenRepair: vi.fn() };
  const { rerender } = render(<RuntimeView {...baseProps} states={stopped} />);

  await userEvent.click(screen.getByRole("button", { name: "전체 실행" }));
  expect(onToggleAll).toHaveBeenCalledWith("start");

  const running = stopped.map((state, index) => ({ ...state, running: true, pid: 100 + index, phase: "ready" as const }));
  rerender(<RuntimeView {...baseProps} states={running} />);
  await userEvent.click(screen.getByRole("button", { name: "전체 중지" }));
  expect(onToggleAll).toHaveBeenCalledWith("stop");
});

test("Docker Compose 인프라를 실행 탭에서 개별 시작한다", async () => {
  const states: ProcessState[] = [
    { target: "backend", running: false, pid: null, port: 8001, phase: "stopped", message: null, command: ["run"] },
    { target: "frontend", running: false, pid: null, port: 5174, phase: "stopped", message: null, command: ["run"] },
  ];
  const stoppedInfrastructure = { docker_available: true, services: [{ name: "mysql", source: "back/compose.yaml", kind: "docker", running: false, status: "stopped", ports: ["3306:3306"], controllable: true }], message: "" };
  apiRequest.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.endsWith("/infrastructure/control") && init?.method === "POST") return { ...stoppedInfrastructure, services: [{ ...stoppedInfrastructure.services[0], running: true, status: "running" }] };
    if (path.endsWith("/infrastructure")) return stoppedInfrastructure;
    if (path.endsWith("/processes")) return states;
    if (path.includes("/logs/chunk")) return { logs: "", cursor: 0, log_id: "", reset: true };
    if (path.endsWith("/technology-stack")) return { backend: [], frontend: [], infrastructure: [] };
    return { disk_bytes: 0, logs_bytes: 0, cache_bytes: 0, versions_bytes: 0, version_count: 0 };
  });
  render(<RuntimeView projectId="demo" states={states} jobs={[]} usage={null} versions={[]} overview={null} costMode="balanced" onStates={vi.fn()} onToggle={vi.fn()} onToggleAll={vi.fn()} onPorts={vi.fn()} onCancel={vi.fn()} onResume={vi.fn()} onClearCache={vi.fn()} onRestore={vi.fn()} onDeleteVersion={vi.fn()} onCostMode={vi.fn()} onOpenRepair={vi.fn()} />);

  await userEvent.click(screen.getByText("인프라 상태"));
  const mysql = await screen.findByText("mysql");
  const card = mysql.closest("article");
  if (!card) throw new Error("mysql infrastructure card not found");
  await userEvent.click(within(card).getByRole("button", { name: "시작" }));

  await waitFor(() => expect(within(card).getByText("running")).toBeTruthy());
  expect(apiRequest).toHaveBeenCalledWith("/projects/demo/infrastructure/control", expect.objectContaining({ method: "POST", body: JSON.stringify({ source: "back/compose.yaml", service: "mysql", action: "start" }), signal: expect.any(AbortSignal) }));
});

test("저장 버전의 파일 차이를 펼쳐서 확인한다", async () => {
  const states: ProcessState[] = [
    { target: "backend", running: false, pid: null, port: 8001, phase: "stopped", message: null, command: [] },
    { target: "frontend", running: false, pid: null, port: 5174, phase: "stopped", message: null, command: [] },
  ];
  apiRequest.mockImplementation(async (path: string) => {
    if (path.endsWith("/processes")) return states;
    if (path.includes("/logs/chunk")) return { logs: "", cursor: 0, log_id: "", reset: true };
    if (path.endsWith("/technology-stack")) return { backend: [], frontend: [], infrastructure: [] };
    if (path.endsWith("/versions/version-1/diff")) return { version_id: "version-1", files: [{ path: "front/app.tsx", status: "modified", additions: 2, deletions: 1, diff: "--- a/front/app.tsx\n+++ b/front/app.tsx", binary: false, truncated: false }], added: 0, modified: 1, deleted: 0, unchanged: 3, runtime_changed: true, truncated_files: 0 };
    return { disk_bytes: 0, logs_bytes: 0, cache_bytes: 0, versions_bytes: 0, version_count: 1 };
  });
  render(<RuntimeView projectId="demo" states={states} jobs={[]} usage={null} versions={[{ id: "version-1", label: "첫 생성", source_job_id: null, created_at: new Date().toISOString() }]} overview={null} costMode="balanced" onStates={vi.fn()} onToggle={vi.fn()} onToggleAll={vi.fn()} onPorts={vi.fn()} onCancel={vi.fn()} onResume={vi.fn()} onClearCache={vi.fn()} onRestore={vi.fn()} onDeleteVersion={vi.fn()} onCostMode={vi.fn()} onOpenRepair={vi.fn()} />);

  await userEvent.click(screen.getByText("저장된 버전 관리"));
  await userEvent.click(screen.getByRole("button", { name: "차이 보기" }));

  await waitFor(() => expect(screen.getByText("front/app.tsx")).toBeTruthy());
  expect(screen.getByText("수정 1")).toBeTruthy();
  expect(screen.getByText("실행 설정 변경")).toBeTruthy();
  expect(apiRequest).toHaveBeenCalledWith("/projects/demo/versions/version-1/diff", expect.objectContaining({ signal: expect.any(AbortSignal) }));
});

test("LLM 요청별 토큰 상세 내역은 펼칠 때만 불러온다", async () => {
  const states: ProcessState[] = [
    { target: "backend", running: false, pid: null, port: 8001, phase: "stopped", message: null, command: [] },
    { target: "frontend", running: false, pid: null, port: 5174, phase: "stopped", message: null, command: [] },
  ];
  apiRequest.mockImplementation(async (path: string) => {
    if (path.includes("/usage/records?")) return [{ id: "usage-1", kind: "planning", model: "gpt-test", provider: "openai", input_tokens: 120, output_tokens: 30, total_tokens: 150, cached_input_tokens: 80, created_at: new Date().toISOString() }];
    if (path.endsWith("/processes")) return states;
    if (path.includes("/logs/chunk")) return { logs: "", cursor: 0, log_id: "", reset: true };
    if (path.endsWith("/technology-stack")) return { backend: [], frontend: [], infrastructure: [] };
    return { disk_bytes: 0, logs_bytes: 0, cache_bytes: 0, versions_bytes: 0, version_count: 0 };
  });
  const usage = { requests: 1, input_tokens: 120, output_tokens: 30, total_tokens: 150, cached_input_tokens: 80, by_kind: {} };
  render(<RuntimeView projectId="demo" states={states} jobs={[]} usage={usage} versions={[]} overview={null} costMode="balanced" onStates={vi.fn()} onToggle={vi.fn()} onToggleAll={vi.fn()} onPorts={vi.fn()} onCancel={vi.fn()} onResume={vi.fn()} onClearCache={vi.fn()} onRestore={vi.fn()} onDeleteVersion={vi.fn()} onCostMode={vi.fn()} onOpenRepair={vi.fn()} />);

  expect(apiRequest).not.toHaveBeenCalledWith(expect.stringContaining("/usage/records?"));
  await userEvent.click(screen.getByText(/요청별 토큰 상세/));

  await waitFor(() => expect(screen.getByText(/openai · gpt-test/)).toBeTruthy());
  expect(screen.getByText("일반 입력")).toBeTruthy();
  expect(screen.getByText("캐시 입력")).toBeTruthy();
  expect(apiRequest).toHaveBeenCalledWith("/projects/demo/usage/records?offset=0&limit=20", expect.objectContaining({ signal: expect.any(AbortSignal) }));
});

test("ZIP 가져오기 대화상자는 파일명으로 서비스 이름을 채우고 업로드한다", async () => {
  const onImport = vi.fn(async () => undefined);
  const onClose = vi.fn();
  render(<ImportServiceDialog onClose={onClose} onImport={onImport} />);
  const file = new File(["archive"], "existing-service.zip", { type: "application/zip" });

  await userEvent.upload(screen.getByLabelText("ZIP 파일"), file);
  expect((screen.getByLabelText("서비스 이름") as HTMLInputElement).value).toBe("existing-service");
  await userEvent.click(screen.getByRole("button", { name: "가져오기" }));

  await waitFor(() => expect(onImport).toHaveBeenCalledWith("existing-service", "기존 ZIP 프로젝트를 Doraemon 서비스로 가져옵니다", file));
  expect(onClose).toHaveBeenCalled();
});

test("서비스 대화상자는 접근 가능한 이름을 제공하고 Esc로 닫힌다", async () => {
  const onClose = vi.fn();
  render(<CreateServiceDialog onClose={onClose} onCreate={vi.fn()} />);

  expect(screen.getByRole("dialog", { name: "새 서비스 시작" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "새 서비스 창 닫기" })).toBeTruthy();
  expect(document.body.style.overflow).toBe("hidden");
  await userEvent.keyboard("{Escape}");

  expect(onClose).toHaveBeenCalledOnce();
});

test("측면 검색에서 작업 결과를 선택하면 해당 서비스 실행 탭으로 이동한다", async () => {
  const project: Project = { id: "travel", name: "Travel", description: "여행 서비스", status: "ready", updated_at: new Date().toISOString(), last_error: null, archived_at: null, llm_policy: { mode: "balanced", planning_source_limit: 40_000, generation_source_limit: 70_000 } };
  apiRequest.mockResolvedValue([{ kind: "job", project_id: "travel", project_name: "Travel", title: "오류 수정 · 지도 마커 오류", subtitle: "marker failed", status: "failed", updated_at: new Date().toISOString() }]);
  const onSelect = vi.fn();
  render(<StudioSidebar projects={[project]} selectedId={null} settingsOpen={false} loading={false} connection="online" activity={{ busy: false, project_id: null, operation: null, estimated_input_tokens: 0, started_at: null }} onSelect={onSelect} onCreate={vi.fn()} onImport={vi.fn()} onSettings={vi.fn()} onTrash={vi.fn()} />);

  await userEvent.type(screen.getByLabelText("서비스·작업 검색"), "marker");
  await userEvent.click(await screen.findByText("오류 수정 · 지도 마커 오류"));

  expect(apiRequest).toHaveBeenCalledWith("/search?q=marker&limit=30", expect.objectContaining({ signal: expect.any(AbortSignal) }));
  expect(onSelect).toHaveBeenCalledWith("travel", "runtime");
});

test("서비스 헤더에서 긴 설명을 펼치고 다시 접을 수 있다", async () => {
  const project: Project = {
    id: "long-description",
    name: "긴 설명 서비스",
    description: "사용자가 서비스의 전체 설명을 필요할 때 확인할 수 있도록 충분히 긴 설명을 제공합니다. ".repeat(4),
    status: "ready",
    updated_at: new Date().toISOString(),
    last_error: null,
    archived_at: null,
    llm_policy: { mode: "balanced", planning_source_limit: 40_000, generation_source_limit: 70_000 },
  };
  const { container } = render(<StudioHeader project={project} notifications={[]} onRead={vi.fn()} onFolder={vi.fn()} onRename={vi.fn()} onClone={vi.fn()} onTrash={vi.fn()} onRefresh={vi.fn()} />);

  const toggle = screen.getByRole("button", { name: "전체 보기" });
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  await userEvent.click(toggle);

  expect(container.querySelector(".service-description")?.classList.contains("expanded")).toBe(true);
  expect(screen.getByRole("button", { name: "접기" }).getAttribute("aria-expanded")).toBe("true");
});

test("서비스 관리 작업 중에는 헤더 작업을 잠그고 진행 상태를 표시한다", () => {
  const project: Project = { id: "busy", name: "Busy", description: "작업 중인 서비스", status: "ready", updated_at: new Date().toISOString(), last_error: null, archived_at: null, llm_policy: { mode: "balanced", planning_source_limit: 40_000, generation_source_limit: 70_000 } };
  const { container } = render(<StudioHeader project={project} notifications={[]} busyAction="clone" onRead={vi.fn()} onFolder={vi.fn()} onRename={vi.fn()} onClone={vi.fn()} onTrash={vi.fn()} onRefresh={vi.fn()} />);

  expect((screen.getByRole("button", { name: "복제 중…" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "폴더" }) as HTMLButtonElement).disabled).toBe(true);
  expect(container.querySelector(".workspace-header")?.getAttribute("aria-busy")).toBe("true");
});

test("작업 내역은 최근 5개만 보이고 종류와 실패 상태로 필터링된다", async () => {
  const states: ProcessState[] = [
    { target: "backend", running: false, pid: null, port: 8001, phase: "stopped", message: null, command: ["python", "-m", "uvicorn"] },
    { target: "frontend", running: false, pid: null, port: 5174, phase: "stopped", message: null, command: ["npm", "run", "dev"] },
  ];
  const jobs: Job[] = Array.from({ length: 7 }, (_, index) => ({
    id: `job-${index}`,
    status: index === 6 ? "failed" : "completed",
    message: index === 6 ? "시작 파일 오류" : `완료 작업 ${index}`,
    error: index === 6 ? "실행 파일 없음" : null,
    updated_at: new Date(2026, 6, 14, 0, index).toISOString(),
    kind: index === 6 ? "repair" : "generation",
    retry_available: index === 6,
    cached_result_available: false,
    interrupted: false,
  }));
  apiRequest.mockImplementation(async (path: string) => {
    if (path.endsWith("/processes")) return states;
    if (path.includes("/logs/chunk")) return { logs: "", cursor: 0, log_id: "", reset: true };
    if (path.endsWith("/technology-stack")) return { backend: [], frontend: [], infrastructure: [] };
    return { disk_bytes: 0, logs_bytes: 0, cache_bytes: 0, versions_bytes: 0, version_count: 0 };
  });
  const { container } = render(<RuntimeView projectId="demo" states={states} jobs={jobs} usage={null} versions={[]} overview={null} costMode="balanced" onStates={vi.fn()} onToggle={vi.fn()} onToggleAll={vi.fn()} onPorts={vi.fn()} onCancel={vi.fn()} onResume={vi.fn()} onClearCache={vi.fn()} onRestore={vi.fn()} onDeleteVersion={vi.fn()} onCostMode={vi.fn()} onOpenRepair={vi.fn()} />);

  expect(container.querySelectorAll(".job-history .job-row").length).toBe(5);
  expect(screen.getByText(/이전 작업 2개 더 보기/)).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "버전" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "실패" }));
  expect(container.querySelectorAll(".job-history .job-row").length).toBe(1);
  expect(screen.getByText(/오류 수정 · 시작 파일 오류/)).toBeTruthy();
});

test("실행 실패 정보는 오류 수정 초안으로 전달된다", async () => {
  const states: ProcessState[] = [
    { target: "backend", running: false, pid: null, port: 8003, phase: "error", message: "module missing", command: ["python", "-m", "uvicorn"] },
    { target: "frontend", running: false, pid: null, port: 5173, phase: "stopped", message: null, command: ["npm", "run", "dev"] },
  ];
  apiRequest.mockImplementation(async (path: string) => {
    if (path.includes("/runtime-snapshot")) return {
      processes: states,
      jobs: [],
      overview: null,
      notifications: [],
      logs: {
        backend: { logs: "backend traceback", cursor: 17, log_id: "backend", reset: true },
        frontend: { logs: "", cursor: 0, log_id: "", reset: true },
      },
    };
    if (path.endsWith("/processes")) return states;
    if (path.includes("/backend/logs/chunk")) return { logs: "backend traceback", cursor: 17, log_id: "backend", reset: true };
    if (path.includes("/frontend/logs/chunk")) return { logs: "", cursor: 0, log_id: "", reset: true };
    if (path.endsWith("/technology-stack")) return { backend: [], frontend: [], infrastructure: [] };
    return { disk_bytes: 0, logs_bytes: 0, cache_bytes: 0, versions_bytes: 0, version_count: 0 };
  });
  const onOpenRepair = vi.fn();
  render(<RuntimeView projectId="demo" states={states} jobs={[]} usage={null} versions={[]} overview={null} costMode="balanced" onStates={vi.fn()} onToggle={vi.fn()} onToggleAll={vi.fn()} onPorts={vi.fn()} onCancel={vi.fn()} onResume={vi.fn()} onClearCache={vi.fn()} onRestore={vi.fn()} onDeleteVersion={vi.fn()} onCostMode={vi.fn()} onOpenRepair={onOpenRepair} />);

  await waitFor(() => expect(screen.getByText("backend traceback")).toBeTruthy());
  await userEvent.click(screen.getByRole("button", { name: "이 로그로 오류 수정" }));
  expect(onOpenRepair).toHaveBeenCalledOnce();
  const draft = onOpenRepair.mock.calls[0][0] as string;
  expect(draft).toContain("python -m uvicorn");
  expect(draft).toContain("module missing");
  expect(draft).toContain("backend traceback");
});

test("로그와 캐시 정리는 처리 중 중복 실행을 막는다", async () => {
  const states: ProcessState[] = [
    { target: "backend", running: false, pid: null, port: 8001, phase: "stopped", message: null, command: ["python", "-m", "uvicorn"] },
    { target: "frontend", running: false, pid: null, port: 5174, phase: "stopped", message: null, command: ["npm", "run", "dev"] },
  ];
  let finishCleanup: (value: unknown) => void = () => undefined;
  const cleanupRequest = new Promise((resolve) => { finishCleanup = resolve; });
  apiRequest.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.includes("/runtime-snapshot")) return { processes: states, jobs: [], overview: null, notifications: [], logs: { backend: { logs: "", cursor: 0, log_id: "", reset: true }, frontend: { logs: "", cursor: 0, log_id: "", reset: true } } };
    if (path.endsWith("/maintenance") && init?.method === "POST") return cleanupRequest;
    if (path.endsWith("/maintenance")) return { disk_bytes: 10, logs_bytes: 5, cache_bytes: 5, versions_bytes: 0, version_count: 0 };
    if (path.endsWith("/technology-stack")) return { backend: [], frontend: [], infrastructure: [] };
    if (path.endsWith("/infrastructure")) return { docker_available: false, services: [], port_settings: [], message: "", errors: [] };
    return null;
  });
  render(<RuntimeView projectId="demo" states={states} jobs={[]} usage={null} versions={[]} overview={null} costMode="balanced" onStates={vi.fn()} onToggle={vi.fn()} onToggleAll={vi.fn()} onPorts={vi.fn()} onCancel={vi.fn()} onResume={vi.fn()} onClearCache={vi.fn()} onRestore={vi.fn()} onDeleteVersion={vi.fn()} onCostMode={vi.fn()} onOpenRepair={vi.fn()} />);

  await userEvent.click(await screen.findByRole("button", { name: "로그·캐시 정리" }));
  const busy = await screen.findByRole("button", { name: "정리 중…" });
  expect((busy as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(busy);
  expect(apiRequest.mock.calls.filter(([path, init]) => path === "/projects/demo/maintenance" && (init as RequestInit)?.method === "POST")).toHaveLength(1);

  finishCleanup({ disk_bytes: 0, logs_bytes: 0, cache_bytes: 0, versions_bytes: 0, version_count: 0 });
  await waitFor(() => expect(screen.getByRole("button", { name: "로그·캐시 정리" })).toBeTruthy());
});

test("오류 수정 초안은 확인만으로 요청하지 않고 명시적으로 전송할 때 요청한다", async () => {
  const onRepair = vi.fn(async () => undefined);
  render(<RepairView initialText="prefilled runtime info" messages={[]} jobs={[]} busy={false} onRepair={onRepair} onCancel={vi.fn()} />);

  expect(screen.getByText(/아직 LLM 요청은 보내지 않았습니다/)).toBeTruthy();
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("prefilled runtime info");
  expect(onRepair).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "오류 수정 시작" }));
  expect(onRepair).toHaveBeenCalledWith("prefilled runtime info");
});

test("환경변수 행을 누르면 기존 키의 값을 수정한다", async () => {
  apiRequest.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      return { values: { API_KEY: "설정됨" }, schema: [{ key: "API_KEY", description: "외부 API", required: false, secret: true, client_exposed: false, format: "text", restart_required: true }] };
    }
    return { values: { API_KEY: "설정됨" }, schema: [{ key: "API_KEY", description: "외부 API", required: false, secret: true, client_exposed: false, format: "text", restart_required: true }] };
  });
  render(<EnvironmentView projectId="demo" onError={vi.fn()} />);

  await userEvent.click(await screen.findByRole("button", { name: /API_KEY/ }));
  await userEvent.type(screen.getByLabelText("새 값"), "replacement");
  await userEvent.click(screen.getByRole("button", { name: "수정" }));

  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(
    "/projects/demo/environment",
    expect.objectContaining({ method: "PUT", body: JSON.stringify({ values: { API_KEY: "replacement" } }), signal: expect.any(AbortSignal) }),
  ));
});

test("환경변수 조회는 서비스가 바뀌면 이전 요청을 취소한다", async () => {
  const pending: Array<{ signal: AbortSignal; resolve: (value: unknown) => void }> = [];
  apiRequest.mockImplementation((_path: string, init?: RequestInit) => new Promise((resolve, reject) => {
    const signal = init?.signal;
    if (!signal) throw new Error("취소 신호가 없습니다");
    signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
    pending.push({ signal, resolve });
  }));
  const onError = vi.fn();
  const view = render(<EnvironmentView projectId="first" onError={onError} />);
  await waitFor(() => expect(pending).toHaveLength(1));

  view.rerender(<EnvironmentView projectId="second" onError={onError} />);
  await waitFor(() => expect(pending).toHaveLength(2));
  expect(pending[0].signal.aborted).toBe(true);
  pending[1].resolve({
    values: { SECOND_KEY: "설정됨" },
    schema: [{ key: "SECOND_KEY", description: "두 번째 서비스", required: false, secret: false, client_exposed: false, format: "text", restart_required: false }],
  });

  expect(await screen.findByRole("button", { name: /SECOND_KEY/ })).toBeTruthy();
  expect(onError).not.toHaveBeenCalled();
});

test("환경변수 저장 중에는 같은 요청을 다시 보내지 않는다", async () => {
  let finishSave: (value: unknown) => void = () => undefined;
  const pendingSave = new Promise((resolve) => { finishSave = resolve; });
  apiRequest.mockImplementation(async (_path: string, init?: RequestInit) => {
    if (init?.method === "PUT") return pendingSave;
    return { values: { API_KEY: "설정됨" }, schema: [{ key: "API_KEY", description: "외부 API", required: false, secret: true, client_exposed: false, format: "text", restart_required: true }] };
  });
  render(<EnvironmentView projectId="demo" onError={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: /API_KEY/ }));
  await userEvent.type(screen.getByLabelText("새 값"), "replacement");
  await userEvent.click(screen.getByRole("button", { name: "수정" }));

  const busy = await screen.findByRole("button", { name: "저장 중…" });
  fireEvent.click(busy);
  expect(apiRequest.mock.calls.filter(([, init]) => (init as RequestInit)?.method === "PUT")).toHaveLength(1);
  finishSave({ values: { API_KEY: "설정됨" }, schema: [] });
  await waitFor(() => expect(screen.queryByRole("button", { name: "저장 중…" })).toBeNull());
});

test("도구 진단 중에는 다른 도구 요청과 중복 진단을 막는다", async () => {
  let finishDiagnostics: (value: unknown) => void = () => undefined;
  const pendingDiagnostics = new Promise((resolve) => { finishDiagnostics = resolve; });
  apiRequest.mockImplementation(async (path: string) => {
    if (path.endsWith("/diagnostics")) return pendingDiagnostics;
    if (path.endsWith("/sqlite")) return [];
    return null;
  });
  render(<ToolsView projectId="demo" onError={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "검사 실행" }));

  const busy = await screen.findByRole("button", { name: "검사 중…" });
  fireEvent.click(busy);
  expect(apiRequest.mock.calls.filter(([path]) => path === "/projects/demo/diagnostics")).toHaveLength(1);
  expect((screen.getByRole("button", { name: "요청" }) as HTMLButtonElement).disabled).toBe(true);
  finishDiagnostics({ security: [], consistency: [], external_services: [] });
  await waitFor(() => expect(screen.getByRole("button", { name: "검사 실행" })).toBeTruthy());
});

test("설정 저장 중에는 입력과 추가 저장 요청을 잠근다", async () => {
  const settings = { default_cost_mode: "balanced", keep_versions: 5, log_tail_lines: 300, log_max_bytes: 2_000_000, notification_retention_days: 30, notification_max_items: 200, llm_provider: "openai", llm_model: "gpt-5.4-mini", llm_base_url: "", llm_api_key_configured: false, llm_api_key_providers: [], llm_max_output_tokens: 64_000, llm_profiles: {} };
  let finishSave: (value: unknown) => void = () => undefined;
  const pendingSave = new Promise((resolve) => { finishSave = resolve; });
  apiRequest.mockImplementation(async (path: string, init?: RequestInit) => path === "/settings" && init?.method === "PUT" ? pendingSave : settings);
  render(<SettingsView onError={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "설정 저장" }));

  const busy = await screen.findByRole("button", { name: "저장 중…" });
  fireEvent.click(busy);
  expect(apiRequest.mock.calls.filter(([path, init]) => path === "/settings" && (init as RequestInit)?.method === "PUT")).toHaveLength(1);
  expect((screen.getByLabelText("모델").closest("fieldset") as HTMLFieldSetElement).disabled).toBe(true);
  finishSave(settings);
  await waitFor(() => expect(screen.getByRole("button", { name: "설정 저장" })).toBeTruthy());
});
