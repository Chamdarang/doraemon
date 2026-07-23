import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { DoraemonStudio } from "../app/studio";
import type { Job, Plan, ProcessState, Project } from "../app/studio-types";

const apiRequest = vi.fn();
vi.mock("../app/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../app/lib/api")>(),
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

Object.defineProperty(Element.prototype, "scrollIntoView", {
  configurable: true,
  value: vi.fn(),
});

const now = "2026-07-14T00:00:00Z";
const implementation = {
  architecture: "로컬 웹 서비스",
  technology_choices: [],
  components: ["API", "Web"],
  directories: [{ path: "back/", purpose: "API" }, { path: "front/", purpose: "Web" }],
  data_and_state: "로컬 상태",
  api_and_integrations: "HTTP API",
  runtime_and_configuration: "로컬 실행",
  testing_strategy: "수동 확인",
};
const completePlan: Plan = {
  draft: {
    reply: "명세가 준비됐습니다.", stage: "review", decisions: ["architecture", "components", "frontend_stack", "backend_stack", "persistence", "repository_layout", "runtime_infrastructure", "testing"].map((category) => ({ category, choice: "확정", rationale: "사용자 선택", confirmed: true })), open_questions: [],
    implementation_plan: implementation, ready_to_generate: true, specification: "완성 명세",
    service_specification: "사용자가 할 일을 관리하는 충분히 구체적인 서비스 명세입니다.",
    technical_specification: "React 프론트엔드와 FastAPI 백엔드로 구성하는 충분히 구체적인 기술 명세입니다.",
  },
  approved: false,
  updated_at: now,
};
const stopped: ProcessState[] = [
  { target: "backend", running: false, pid: null, port: 8001, phase: "stopped", message: null, command: ["python", "-m", "uvicorn"] },
  { target: "frontend", running: false, pid: null, port: 5174, phase: "stopped", message: null, command: ["npm", "run", "dev"] },
];

function project(id: string, name: string): Project {
  return { id, name, description: `${name} 설명`, status: "draft", updated_at: now, last_error: null, archived_at: null, llm_policy: { mode: "balanced", planning_source_limit: 40_000, generation_source_limit: 70_000 } };
}

function installApi(initialProjects = [project("alpha", "Alpha")], activityProject: string | null = null) {
  let projects = [...initialProjects];
  let plan: Plan | null = null;
  let jobs: Job[] = [];
  const versions = [{ id: "version-1", label: "첫 생성", source_job_id: null, created_at: now }];
  const settings = {
    default_cost_mode: "balanced", keep_versions: 5, log_tail_lines: 300, log_max_bytes: 2_000_000,
    notification_retention_days: 30, notification_max_items: 200,
    llm_provider: "openai", llm_model: "gpt-5.4-mini", llm_base_url: "", llm_api_key_configured: false,
    llm_api_key_providers: [], llm_max_output_tokens: 64_000, llm_profiles: {},
  };
  apiRequest.mockImplementation(async (path: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (path === "/settings/llm/activity") return { busy: Boolean(activityProject), project_id: activityProject, operation: activityProject ? "generation" : null, estimated_input_tokens: activityProject ? 1200 : 0, started_at: activityProject ? now : null };
    if (path === "/settings" && method === "GET") return settings;
    if (path === "/settings" && method === "PUT") return { ...settings, ...JSON.parse(String(init?.body ?? "{}")) };
    if (path === "/projects" && method === "GET") return projects;
    if (path === "/projects/overviews" && method === "GET") return projects.map((item) => ({ project_id: item.id, backend_running: false, frontend_running: false, missing_environment: [], health: [] }));
    if (path === "/projects" && method === "POST") {
      const body = JSON.parse(String(init?.body));
      const created = project("new-service", body.name);
      created.description = body.description;
      projects = [created, ...projects];
      return created;
    }
    if (path === "/trash") return [{ id: "trash-1", project_id: "restored", name: "복구 서비스", description: "복구할 서비스", deleted_at: now }];
    if (path === "/trash/trash-1/restore") {
      const restored = project("restored", "복구 서비스");
      projects = [restored, ...projects];
      return restored;
    }
    if (path.endsWith("/workspace")) {
      const projectId = path.split("/")[2];
      return {
        messages: [], jobs, processes: stopped, improvement_messages: [], plan,
        improvement_plan: null,
        usage: { requests: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0, cached_input_tokens: 0, by_kind: {} },
        versions, repair_messages: [],
        overview: { project_id: projectId, backend_running: false, frontend_running: false, missing_environment: [], health: [] },
        notifications: [],
      };
    }
    if (/\/overview/.test(path)) return { project_id: path.split("/")[2], backend_running: false, frontend_running: false, missing_environment: [], health: [] };
    if (path.endsWith("/messages") && method === "POST" && !path.includes("improvements")) {
      plan = completePlan;
      return { assistant_message: { id: "assistant-1", role: "assistant", content: "명세가 준비됐습니다.", created_at: now }, plan };
    }
    if (path.endsWith("/messages")) return [];
    if (path.endsWith("/plan/approve")) { plan = { ...completePlan, approved: true }; return plan; }
    if (path.endsWith("/generate")) {
      const job: Job = { id: "job-1", status: "queued", message: "생성 대기", error: null, updated_at: now, kind: "generation", retry_available: false, cached_result_available: false, interrupted: false };
      jobs = [job];
      return job;
    }
    if (path.endsWith("/plan")) return plan;
    if (path.endsWith("/improvement")) return null;
    if (path.endsWith("/jobs")) return jobs;
    if (path.endsWith("/processes/backend/start")) throw new Error("backend start failed");
    if (path.endsWith("/processes")) return stopped;
    if (path.includes("/logs/chunk")) return { logs: path.includes("backend") ? "backend traceback" : "", cursor: 17, log_id: "log", reset: true };
    if (path.endsWith("/usage")) return { requests: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0, cached_input_tokens: 0, by_kind: {} };
    if (path.endsWith("/versions")) return versions;
    if (path.endsWith("/versions/version-1/restore")) return versions[0];
    if (path.endsWith("/notifications")) return [];
    if (path.endsWith("/technology-stack")) return { backend: [], frontend: [], infrastructure: [] };
    if (path.endsWith("/maintenance")) return { disk_bytes: 0, logs_bytes: 0, cache_bytes: 0, versions_bytes: 0, version_count: versions.length };
    if (path.endsWith("/improvements/messages") || path.endsWith("/repairs/messages")) return [];
    return null;
  });
}

beforeEach(() => installApi());
afterEach(() => { cleanup(); vi.clearAllMocks(); });

test("서비스 선택 상세 정보는 단일 워크스페이스 스냅샷으로 불러온다", async () => {
  render(<DoraemonStudio />);
  expect(await screen.findByRole("heading", { name: "Alpha" })).toBeTruthy();
  expect(screen.getByRole("tab", { name: "기획" }).getAttribute("aria-selected")).toBe("true");

  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("/projects/alpha/workspace", expect.objectContaining({ signal: expect.any(AbortSignal) })));
  const legacyDetailPaths = ["messages", "jobs", "processes", "plan", "improvement", "usage", "versions", "notifications"];
  expect(apiRequest.mock.calls.some(([path]) => legacyDetailPaths.some((suffix) => path === `/projects/alpha/${suffix}`))).toBe(false);
});

test("새 서비스 생성부터 기획 승인과 생성 후 실행 탭 전환까지 연결된다", async () => {
  render(<DoraemonStudio />);
  await userEvent.click(await screen.findByRole("button", { name: /새 서비스/ }));
  await userEvent.type(screen.getByLabelText("서비스 이름"), "새 서비스");
  await userEvent.type(screen.getByLabelText("만들고 싶은 서비스"), "사용자가 매일 할 일을 간단하게 관리하는 서비스입니다.");
  await userEvent.click(screen.getByRole("button", { name: "기획 시작하기" }));
  expect(await screen.findByRole("heading", { name: "새 서비스" })).toBeTruthy();

  await userEvent.type(screen.getByPlaceholderText("답변하거나 새로운 요구사항을 입력하세요"), "추천 구성으로 정리해줘");
  await userEvent.keyboard("{Enter}");
  expect(await screen.findByText("명세가 준비됐습니다.")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: /현재 명세 승인하고 생성/ }));

  expect(await screen.findByRole("heading", { name: "서비스 미리보기" })).toBeTruthy();
  expect(apiRequest).toHaveBeenCalledWith("/projects/new-service/generate", expect.objectContaining({ method: "POST", signal: expect.any(AbortSignal) }));
});

test("다른 서비스의 LLM 작업을 표시하고 공급자 설정을 저장한다", async () => {
  cleanup(); apiRequest.mockReset(); installApi([project("alpha", "Alpha"), project("beta", "Beta")], "beta");
  render(<DoraemonStudio />);
  const activity = await screen.findByText("LLM 작업 중");
  expect(activity.closest(".project-item")?.textContent).toContain("Beta");

  await userEvent.click(screen.getByRole("button", { name: /Doraemon 설정/ }));
  await userEvent.selectOptions(await screen.findByLabelText("공급자"), "anthropic");
  await userEvent.click(screen.getByRole("button", { name: "설정 저장" }));
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("/settings", expect.objectContaining({ method: "PUT" })));
  const settingsCall = apiRequest.mock.calls.find(([path, init]) => path === "/settings" && (init as RequestInit)?.method === "PUT");
  expect(JSON.parse(String((settingsCall?.[1] as RequestInit).body)).llm_provider).toBe("anthropic");
});

test("휴지통 복구, 버전 복원, 실행 실패의 오류 수정 연결이 동작한다", async () => {
  const { container } = render(<DoraemonStudio />);
  await userEvent.click(await screen.findByRole("button", { name: "휴지통" }));
  await userEvent.click(await screen.findByRole("button", { name: "복구" }));
  expect(await screen.findByRole("heading", { name: "복구 서비스" })).toBeTruthy();

  await userEvent.click(screen.getByRole("tab", { name: "실행" }));
  await userEvent.click(await screen.findByRole("button", { name: "복원" }));
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("/projects/restored/versions/version-1/restore", { method: "POST" }));

  const backendCard = container.querySelector<HTMLElement>(".runtime-card.service-runtime.phase-stopped");
  if (!backendCard) throw new Error("백엔드 실행 카드를 찾지 못했습니다");
  await userEvent.click(within(backendCard).getByRole("button", { name: "시작" }));
  expect(screen.getByText("로컬 API 연결됨")).toBeTruthy();
  await userEvent.click(await within(backendCard).findByRole("button", { name: "이 로그로 오류 수정" }));
  expect((await screen.findByPlaceholderText(/프론트 시작 시 빈 화면/) as HTMLTextAreaElement).value).toContain("backend start failed");
});

test("헤더 작업 실패는 연결 상태와 분리된 화면 오류로 처리한다", async () => {
  const original = apiRequest.getMockImplementation();
  apiRequest.mockImplementation(async (...args: unknown[]) => {
    if (args[0] === "/projects/alpha/open-folder") throw new Error("폴더를 열 수 없습니다");
    return original?.(...args);
  });
  render(<DoraemonStudio />);

  await userEvent.click(await screen.findByRole("button", { name: "폴더" }));

  expect((await screen.findByRole("alert")).textContent).toContain("폴더를 열 수 없습니다");
  expect(screen.getByText("로컬 API 연결됨")).toBeTruthy();
});
