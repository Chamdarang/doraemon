import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the Doraemon shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /<title>Doraemon<\/title>/i);
  assert.match(html, /새 서비스/);
  assert.match(html, /서비스 목록/);
  assert.match(html, /Doraemon을 준비하고 있어요/);
  assert.doesNotMatch(html, /Your site is taking shape/);
});

test("keeps API configuration external and exposes the core studio flows", async () => {
  const [studio, api, layout, page, workspaceHook, baseStyles, themeStyles] = await Promise.all([
    readFile(new URL("../app/studio.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/hooks/use-project-workspace.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../app/styles/theme.css", import.meta.url), "utf8"),
  ]);
  const styles = `${baseStyles}\n${themeStyles}`;
  assert.match(api, /NEXT_PUBLIC_POCKET_API_URL/);
  assert.doesNotMatch(api + studio, /sk-[A-Za-z0-9_-]+/);
  assert.match(studio, />기획<\/button>/);
  assert.match(studio, />개선<\/button>/);
  assert.match(studio, />오류 수정<\/button>/);
  assert.match(studio, />실행<\/button>/);
  assert.match(studio, />환경변수<\/button>/);
  assert.match(layout, /lang="ko"/);
  assert.match(page, /<DoraemonStudio \/>/);
  const activityRefresh = workspaceHook.slice(workspaceHook.indexOf("const refreshActivity"), workspaceHook.indexOf("useEffect(() =>", workspaceHook.indexOf("const refreshActivity")));
  assert.match(activityRefresh, /\/runtime-snapshot\?include_logs=false/);
  assert.doesNotMatch(activityRefresh, /`\/projects\/\$\{projectId\}\/jobs|`\/projects\/\$\{projectId\}\/processes/);
  assert.doesNotMatch(activityRefresh, /\/messages|\/plan|\/usage|\/versions/);
  assert.match(styles, /--accent:#1683d8/);
  assert.match(styles, /linear-gradient\(180deg,#0875c1/);
  assert.match(styles, /\.workspace-header \{ position:relative; z-index:30; overflow:visible;/);
  assert.match(styles, /\.notification-center\{position:relative;z-index:2\}/);
});

test("launcher records only ready processes and stops the previous owned instance", async () => {
  const [startScript, stopScript] = await Promise.all([
    readFile(new URL("../../start.cmd", import.meta.url), "utf8"),
    readFile(new URL("../../stop.cmd", import.meta.url), "utf8"),
  ]);
  assert.match(startScript, /if exist "\.pocket-runtime\\ports\.cmd" call .*stop\.cmd/);
  assert.match(startScript, /if not defined API_PID goto api_failed/);
  assert.match(startScript, /if not defined WEB_PID goto web_failed/);
  assert.match(startScript, /move \/y "\.pocket-runtime\\ports\.tmp" "\.pocket-runtime\\ports\.cmd"/);
  assert.doesNotMatch(startScript, /timeout \/t/);
  assert.match(stopScript, /if "%%P"=="%~2" taskkill \/PID %%P \/T \/F/);
});
