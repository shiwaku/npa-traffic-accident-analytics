import { connect, runTool, type Session } from "./host";

// 段階Aの確認用。引数は固定（DESIGN_WEB.md 9章）
const PRESETS: { label: string; tool: string; args: Record<string, unknown> }[] = [
  { label: "生活道路ダッシュボード（全国）", tool: "seikatsu_dashboard", args: {} },
  { label: "年別の集計表", tool: "aggregate", args: { group_by: ["year"] } },
  { label: "事故地点マップ（東京都・生活道路）", tool: "accident_map", args: { prefecture: ["東京都"], seikatsu: "strict" } },
];

const statusEl = document.getElementById("status")!;
const presetsEl = document.getElementById("presets")!;
const viewsEl = document.getElementById("views")!;

let current: { close(): Promise<void> } | null = null;

async function show(s: Session, p: (typeof PRESETS)[number]): Promise<void> {
  for (const b of presetsEl.querySelectorAll("button")) b.disabled = true;
  statusEl.textContent = `${p.label} を集計中…`;
  const t0 = performance.now();
  try {
    await current?.close();
    current = null;
    viewsEl.replaceChildren();
    const h = await runTool(s, p.tool, p.args, viewsEl);
    const r = await h.result;
    if (h.frame) current = h as { close(): Promise<void> };
    if (r.isError) throw new Error(r.content.map((c) => ("text" in c ? c.text : "")).join("\n"));
    statusEl.textContent = `${p.label}: ${((performance.now() - t0) / 1000).toFixed(1)} 秒`;
  } catch (e) {
    statusEl.textContent = `失敗: ${e instanceof Error ? e.message : String(e)}`;
  } finally {
    for (const b of presetsEl.querySelectorAll("button")) b.disabled = false;
  }
}

connect()
  .then((s) => {
    statusEl.textContent = `接続済み（ツール ${s.tools.size} 個）`;
    for (const p of PRESETS) {
      if (!s.tools.has(p.tool)) continue;
      const b = document.createElement("button");
      b.textContent = p.label;
      b.addEventListener("click", () => void show(s, p));
      presetsEl.append(b);
    }
    presetsEl.hidden = false;
  })
  .catch((e) => {
    statusEl.textContent = `接続できない: ${e instanceof Error ? e.message : String(e)}`;
  });
