import type { Metadata } from "next";
import { DoraemonStudio } from "./studio";

export const metadata: Metadata = {
  title: "Doraemon",
  description: "아이디어를 실제 서비스로 만드는 로컬 AI 스튜디오",
};

export default function Home() {
  return <DoraemonStudio />;
}
