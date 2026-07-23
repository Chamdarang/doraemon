import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test } from "vitest";

import { GenerationCoverage } from "../app/features/generation-coverage";

afterEach(cleanup);

test("생성 결과 대응표에서 구현 항목과 주요 파일을 확인한다", async () => {
  render(<GenerationCoverage value={{
    screens: ["대시보드"],
    apis: ["GET /api/items"],
    core_flows: ["항목 조회"],
    limitations: ["오프라인 미지원"],
    key_files: [{ path: "front/src/App.tsx", purpose: "메인 화면" }],
  }} />);

  await userEvent.click(screen.getByText("생성 결과 대응표"));

  expect(screen.getByText("대시보드")).toBeTruthy();
  expect(screen.getByText("GET /api/items")).toBeTruthy();
  expect(screen.getByText("front/src/App.tsx")).toBeTruthy();
});
