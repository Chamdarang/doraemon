import type { GenerationCoverage as Coverage } from "../studio-types";

export function GenerationCoverage({ value }: { value: Coverage }) {
  const groups = [
    ["화면", value.screens],
    ["API", value.apis],
    ["핵심 흐름", value.core_flows],
    ["제한사항", value.limitations],
  ] as const;
  const count = groups.reduce((sum, [, items]) => sum + items.length, 0) + value.key_files.length;
  if (count === 0) return null;
  return <details className="generation-coverage">
    <summary>생성 결과 대응표 <b>{count}</b></summary>
    <div>
      {groups.map(([label, items]) => items.length > 0 && <section key={label}><strong>{label}</strong><ul>{items.map((item) => <li key={item}>{item}</li>)}</ul></section>)}
      {value.key_files.length > 0 && <section><strong>주요 파일</strong><dl>{value.key_files.map((item) => <div key={item.path}><dt>{item.path}</dt><dd>{item.purpose}</dd></div>)}</dl></section>}
    </div>
  </details>;
}
