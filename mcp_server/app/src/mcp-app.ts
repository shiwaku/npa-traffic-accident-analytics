/**
 * @file 生活道路ダッシュボードのビュー。
 *
 * ホストとのやり取りは MCP Apps SDK の `App` に任せる（ui/initialize の
 * ハンドシェイク、tool-result の受信、tools/call の送出、サイズ通知）。
 * このファイルが持つのは描画と、strict/broad の切り替えだけ。
 */
import {
  App,
  applyDocumentTheme,
  applyHostFonts,
  applyHostStyleVariables,
  type McpUiHostContext,
} from "@modelcontextprotocol/ext-apps";
import type { CallToolResult } from "@modelcontextprotocol/client";
import "./mcp-app.css";

/** Python 側 `seikatsu_dashboard` が structuredContent で返す形。 */
interface Year {
  年: number;
  全事故件数: number;
  件数: number;
  死者数: number;
  負傷者数: number;
  死亡事故: number;
  若年歩行者自転車: number;
  ゾーン30: number;
  指数: number;
  全事故指数: number;
  構成比: number;
  若年構成比: number;
}
interface Payload {
  scope: string;
  definition: { seikatsu: "strict" | "broad"; label: string; description: string; road_width_labels: string[] };
  args: { seikatsu: string; year_from: number; year_to: number; prefecture: string[] | null };
  years: Year[];
  totals: Record<string, number>;
  notes: string[];
  sql: string;
}

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const mainEl = document.querySelector(".main") as HTMLElement;
const scopeEl = $("scope");
const defnEl = $("defn");
const kpisEl = $("kpis");
const chartEl = $("chart");
const chartCapEl = $("chart-cap");
const tbodyEl = $("tbody");
const notesEl = $("notes");
const sqlEl = $("sql");
const errEl = $("err");
const buttons = Array.from(document.querySelectorAll<HTMLButtonElement>(".switch button"));

const nf = new Intl.NumberFormat("ja-JP");
const pct = (x: number, d = 1) => (x * 100).toFixed(d) + "%";

let state: Payload | null = null;

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}

function apply(result: CallToolResult): void {
  const d = result.structuredContent as Payload | undefined;
  if (!d?.years?.length) return;
  state = d;
  render();
}

function render(): void {
  const d = state;
  if (!d) return;
  const y = d.years;
  const t = d.totals;

  for (const b of buttons) {
    b.setAttribute("aria-pressed", String(b.dataset.v === d.definition.seikatsu));
    b.disabled = false;
  }

  scopeEl.textContent = d.scope;
  defnEl.innerHTML =
    `<b>${esc(d.definition.label)}</b>　${esc(d.definition.description)}` +
    `<br>車道幅員: ${esc(d.definition.road_width_labels.join(" / "))}`;

  kpisEl.innerHTML = (
    [
      ["期間合計 件数", nf.format(t.件数), "全事故の " + pct(t.構成比)],
      ["死亡事故", nf.format(t.死亡事故) + "件", "死者 " + nf.format(t.死者数) + "人"],
      ["0〜24歳の歩行者・自転車", nf.format(t.若年歩行者自転車), "構成比 " + pct(t.若年構成比)],
      ["ゾーン30内", nf.format(t.ゾーン30), "構成比 " + pct(t.ゾーン30構成比)],
    ] as const
  )
    .map(([k, v, s]) => `<div class="kpi"><div class="k">${esc(k)}</div><div class="v">${v}</div><div class="s">${esc(s)}</div></div>`)
    .join("");

  chartCapEl.textContent = `件数（棒）と指数（線, ${y[0].年}年=100）`;
  chartEl.innerHTML = chart(y);

  tbodyEl.innerHTML = y
    .map(
      (r) =>
        `<tr><td>${r.年}</td><td>${nf.format(r.件数)}</td><td>${r.指数.toFixed(0)}</td>` +
        `<td>${pct(r.構成比)}</td><td>${nf.format(r.死亡事故)}</td><td>${nf.format(r.死者数)}</td>` +
        `<td>${nf.format(r.若年歩行者自転車)} <span class="pc">${pct(r.若年構成比, 0)}</span></td>` +
        `<td>${nf.format(r.ゾーン30)}</td></tr>`,
    )
    .join("");

  notesEl.innerHTML = d.notes.map((n) => `<li>${esc(n)}</li>`).join("");
  sqlEl.textContent = d.sql;
  errEl.hidden = true;
  mainEl.classList.remove("busy");
}

/**
 * 件数の棒に、生活道路と全事故の指数を重ねる。
 * 母数の線がないと、減っているのが生活道路だけなのか全体なのかが読めない。
 */
function chart(y: Year[]): string {
  const W = 640, H = 196, ml = 46, mr = 40, mt = 16, mb = 26;
  const iw = W - ml - mr, ih = H - mt - mb, bw = iw / y.length;
  const maxC = Math.max(...y.map((r) => r.件数));
  const step = maxC > 90000 ? 30000 : 20000;
  const topC = Math.ceil(maxC / step) * step;
  const idx = [...y.map((r) => r.指数), ...y.map((r) => r.全事故指数), 100];
  const lo = Math.floor((Math.min(...idx) - 8) / 5) * 5;
  const hi = Math.ceil((Math.max(...idx) + 8) / 5) * 5;
  const xc = (i: number) => ml + bw * (i + 0.5);
  const yb = (v: number) => mt + ih - (v / topC) * ih;
  const yi = (v: number) => mt + ih - ((v - lo) / (hi - lo)) * ih;

  const p: string[] = [`<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`];
  for (let v = 0; v <= topC; v += step) {
    p.push(`<line class="g" x1="${ml}" y1="${yb(v).toFixed(1)}" x2="${W - mr}" y2="${yb(v).toFixed(1)}"/>`);
    p.push(`<text class="ax" x="${ml - 8}" y="${(yb(v) + 3.5).toFixed(1)}" text-anchor="end">${v / 1000}k</text>`);
  }
  p.push(`<line class="base" x1="${ml}" y1="${yi(100).toFixed(1)}" x2="${W - mr}" y2="${yi(100).toFixed(1)}"/>`);
  p.push(`<text class="ax" x="${W - mr + 5}" y="${(yi(100) + 3.5).toFixed(1)}">100</text>`);
  y.forEach((r, i) => {
    const top = yb(r.件数);
    p.push(`<rect class="bar" x="${(ml + bw * i + bw * 0.24).toFixed(1)}" y="${top.toFixed(1)}" width="${(bw * 0.52).toFixed(1)}" height="${Math.max(mt + ih - top, 0).toFixed(1)}" rx="2"/>`);
    p.push(`<text class="yr" x="${xc(i).toFixed(1)}" y="${H - 9}" text-anchor="middle">${r.年}</text>`);
  });
  const line = (key: "指数" | "全事故指数", cls: string) => {
    const pts = y.map((r, i) => `${xc(i).toFixed(1)},${yi(r[key]).toFixed(1)}`).join(" ");
    p.push(`<polyline class="${cls}" points="${pts}"/>`);
  };
  line("全事故指数", "l-total");
  line("指数", "l-road");
  y.forEach((r, i) => {
    p.push(`<circle class="d-road" cx="${xc(i).toFixed(1)}" cy="${yi(r.指数).toFixed(1)}" r="3"/>`);
    p.push(`<text class="vlab" x="${xc(i).toFixed(1)}" y="${(yi(r.指数) - 9).toFixed(1)}" text-anchor="middle">${r.指数.toFixed(0)}</text>`);
  });
  p.push("</svg>");
  return p.join("");
}

function handleHostContextChanged(ctx: McpUiHostContext): void {
  if (ctx.theme) applyDocumentTheme(ctx.theme);
  if (ctx.styles?.variables) applyHostStyleVariables(ctx.styles.variables);
  if (ctx.styles?.css?.fonts) applyHostFonts(ctx.styles.css.fonts);
  if (ctx.safeAreaInsets) {
    const { top, right, bottom, left } = ctx.safeAreaInsets;
    mainEl.style.padding = `${top + 14}px ${right + 14}px ${bottom + 14}px ${left + 14}px`;
  }
}

// 1. App を作る
const app = new App({ name: "npa-seikatsu-dashboard", version: "1.0.0" });

// 2. ハンドラは connect() の前に全部登録する
app.ontoolresult = apply;
app.ontoolinput = () => {
  mainEl.classList.add("busy");
};
app.ontoolcancelled = (params) => {
  errEl.textContent = "集計が中断された: " + params.reason;
  errEl.hidden = false;
  mainEl.classList.remove("busy");
};
app.onhostcontextchanged = handleHostContextChanged;
app.onteardown = async () => ({});
app.onerror = (e) => console.error("[seikatsu]", e);

// strict ⇄ broad。会話に戻らず、ビューから同じツールを呼び直す
for (const b of buttons) {
  b.addEventListener("click", async () => {
    if (!state || state.definition.seikatsu === b.dataset.v) return;
    mainEl.classList.add("busy");
    for (const x of buttons) x.disabled = true;
    try {
      const result = await app.callServerTool({
        name: "seikatsu_dashboard",
        arguments: {
          seikatsu: b.dataset.v,
          year_from: state.args.year_from,
          year_to: state.args.year_to,
          prefecture: state.args.prefecture,
        },
      });
      apply(result);
    } catch (e) {
      errEl.textContent = "再集計に失敗した: " + (e instanceof Error ? e.message : String(e));
      errEl.hidden = false;
      mainEl.classList.remove("busy");
      for (const x of buttons) x.disabled = false;
    }
  });
}

// 3. 接続
app.connect().then(() => {
  const ctx = app.getHostContext();
  if (ctx) handleHostContextChanged(ctx);
});
