/**
 * @file 事故地点マップのビュー。
 *
 * ホストとのやり取りは MCP Apps SDK の `App` に任せ、このファイルは描画と操作だけを持つ。
 * 背景地図は地理院の最適化ベクトルタイル（淡色）。サンドボックスiframeからの通信は
 * サーバー側が宣言した CSP のドメインにだけ通る（accident_map.py を参照）。
 *
 * 操作の切り分け:
 *   - 生活道路の定義 / 死亡事故のみ … サーバーを呼び直す。件数(該当)自体が変わるため
 *   - 年 … 受け取った点を絞るだけ。再問い合わせせず即座に効く
 */
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  App,
  applyDocumentTheme,
  applyHostFonts,
  applyHostStyleVariables,
  type McpUiHostContext,
} from "@modelcontextprotocol/ext-apps";
import type { CallToolResult } from "@modelcontextprotocol/client";
import type { FeatureCollection, Point as GeoPoint } from "geojson";
import { basemapStyle } from "./gsi-style";
import "./map-app.css";

/** Python 側 `accident_map` が structuredContent で返す形。点は配列（キー名だけで数百KBになるため）。 */
type Point = [
  lon: number, lat: number, year: number, fatal: 0 | 1,
  accidentType: number, typeA: number, typeB: number,
  width: number, dayNight: number, zone30: 0 | 1, prefecture: number,
];

interface Payload {
  scope: string;
  args: Record<string, unknown> & { seikatsu: "strict" | "broad" | null; fatal_only: boolean };
  counts: { 該当: number; 描画: number; 抽出: boolean; 座標なし: number };
  legend: { 事故類型: string[]; 種別: string[]; 車道幅員: string[]; 昼夜: string[]; 都道府県: string[] };
  points: Point[];
  bounds: [number, number, number, number];
  /** fitBounds の拡大上限。サーバーが用途に応じて決める（半径指定なら深く寄る） */
  max_zoom?: number;
  notes: string[];
  sql: string;
}

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const mainEl = document.querySelector(".main") as HTMLElement;
const scopeEl = $("scope");
const countsEl = $("counts");
const warnEl = $("warn");
const yearsEl = $("years");
const notesEl = $("notes");
const sqlEl = $("sql");
const errEl = $("err");
const expandEl = $<HTMLButtonElement>("expand");
const fatalEl = $<HTMLInputElement>("fatal");
const seikatsuButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("[data-seikatsu]"));

const nf = new Intl.NumberFormat("ja-JP");
const SRC = "accidents";
const LAYER = "accidents-circle";

let state: Payload | null = null;
let theme: "light" | "dark" = "light";
let displayMode = "inline";
/** 表示する年。空なら全部 */
let shownYears = new Set<number>();

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}

/**
 * CSS変数の色を、MapLibre が読める形（rgb(...)）に解決して返す。
 *
 * getPropertyValue は宣言をそのまま返すため、`light-dark(#a, #b)` のまま渡すことになり
 * MapLibre は "Could not parse color" でそのレイヤーを描かない。エラーは出るが地図自体は
 * 表示されるので気付きにくい。ダミー要素に載せて算出値を読むと解決済みの色になる。
 */
function cssColor(name: string, fallback: string): string {
  const probe = document.createElement("span");
  probe.style.cssText = `display:none;color:var(${name},${fallback})`;
  document.body.append(probe);
  const v = getComputedStyle(probe).color;
  probe.remove();
  return v || fallback;
}

const map = new maplibregl.Map({
  container: "map",
  style: basemapStyle(theme),
  center: [138.5, 37.5],
  zoom: 4.2,
  minZoom: 4,
  maxZoom: 18,
  attributionControl: false,
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }), "bottom-right");
map.addControl(
  new maplibregl.AttributionControl({
    compact: true,
    customAttribution: "事故データ: 警察庁 交通事故統計情報のオープンデータ",
  }),
);

function toGeoJson(points: Point[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: points.map((p) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [p[0], p[1]] },
      properties: { y: p[2], f: p[3], at: p[4], a: p[5], b: p[6], w: p[7], dn: p[8], z: p[9], pr: p[10] },
    })),
  };
}

/**
 * 点のレイヤーを貼る。背景スタイルを差し替えると全レイヤーが消えるので、
 * テーマ切替のたびに呼び直す。1点=1事故で、重なりの濃さは密度であって件数の目盛りではない。
 */
function addLayers(): void {
  if (!state) return;
  if (!map.getSource(SRC)) {
    map.addSource(SRC, { type: "geojson", data: toGeoJson(state.points) });
  }
  if (map.getLayer(LAYER)) return;
  map.addLayer({
    id: LAYER,
    type: "circle",
    source: SRC,
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 1.6, 9, 3.2, 14, 6, 18, 11],
      "circle-color": ["case", ["==", ["get", "f"], 1],
        cssColor("--pt-fatal", "#c62f1c"), cssColor("--pt-injury", "#1d5fa8")],
      "circle-opacity": ["interpolate", ["linear"], ["zoom"], 4, 0.55, 12, 0.8],
      "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 10, 0, 13, 0.8],
      "circle-stroke-color": cssColor("--color-background-primary", "#ffffff"),
    },
    // 死亡事故は数が少ない。負傷の点に埋もれないよう上に描く
    layout: { "circle-sort-key": ["get", "f"] },
  });
  applyPointFilter();
}

function applyPointFilter(): void {
  if (!map.getLayer(LAYER)) return;
  map.setFilter(LAYER, shownYears.size ? ["in", ["get", "y"], ["literal", [...shownYears]]] : null);
  renderCounts();
}

function renderCounts(): void {
  if (!state) return;
  const c = state.counts;
  const shown = shownYears.size ? state.points.filter((p) => shownYears.has(p[2])).length : c.描画;
  const parts = [`該当 <b>${nf.format(c.該当)}</b>件`];
  if (c.抽出) parts.push(`描画 ${nf.format(c.描画)}件`);
  if (shown !== c.描画) parts.push(`表示 ${nf.format(shown)}件`);
  countsEl.innerHTML = parts.join("　/　");
}

function renderYearChips(): void {
  if (!state) return;
  const years = [...new Set(state.points.map((p) => p[2]))].sort();
  yearsEl.innerHTML = years
    .map((y) => `<button type="button" data-year="${y}" aria-pressed="${shownYears.has(y)}">${y}</button>`)
    .join("");
  for (const b of yearsEl.querySelectorAll<HTMLButtonElement>("button")) {
    b.addEventListener("click", () => {
      const y = Number(b.dataset.year);
      if (shownYears.has(y)) shownYears.delete(y);
      else shownYears.add(y);
      b.setAttribute("aria-pressed", String(shownYears.has(y)));
      applyPointFilter();
    });
  }
}

function apply(result: CallToolResult): void {
  const d = result.structuredContent as Payload | undefined;
  if (!d?.points) return;
  state = d;
  shownYears = new Set();

  scopeEl.textContent = d.scope;
  warnEl.hidden = !d.counts.抽出;
  if (d.counts.抽出) {
    warnEl.textContent =
      `該当 ${nf.format(d.counts.該当)}件のうち ${nf.format(d.counts.描画)}件を無作為抽出して描いている。`
      + "点の密度は比べられるが、点を数えても事故件数にはならない。";
  }
  for (const b of seikatsuButtons) {
    b.setAttribute("aria-pressed", String((b.dataset.seikatsu ?? "none") === (d.args.seikatsu ?? "none")));
    b.disabled = false;
  }
  fatalEl.checked = d.args.fatal_only;
  fatalEl.disabled = false;

  renderYearChips();
  renderCounts();
  notesEl.innerHTML = d.notes.map((n) => `<li>${esc(n)}</li>`).join("");
  sqlEl.textContent = d.sql;
  errEl.hidden = true;
  mainEl.classList.remove("busy");

  const src = map.getSource(SRC) as maplibregl.GeoJSONSource | undefined;
  if (src) src.setData(toGeoJson(d.points));
  else if (map.isStyleLoaded()) addLayers();
  else map.once("idle", addLayers);

  const [w, s, e, n] = d.bounds;
  map.fitBounds([[w, s], [e, n]], { padding: 36, maxZoom: d.max_zoom ?? 15, duration: 0 });
}

function popupHtml(props: Record<string, unknown>): string {
  const L = state!.legend;
  const rows: [string, string][] = [
    ["都道府県", L.都道府県[props.pr as number] ?? "不明"],
    ["事故類型", L.事故類型[props.at as number] ?? "不明"],
    ["当事者A", L.種別[props.a as number] ?? "不明"],
    ["当事者B", L.種別[props.b as number] ?? "不明"],
    ["車道幅員", L.車道幅員[props.w as number] ?? "不明"],
    ["昼夜", L.昼夜[props.dn as number] ?? "不明"],
  ];
  if (props.z === 1) rows.push(["ゾーン規制", "ゾーン30"]);
  return (
    `<div class="pop"><div class="pop-h">${props.y}年　`
    + (props.f === 1 ? '<span class="fatal">死亡事故</span>' : "負傷事故")
    + "</div><dl>"
    + rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")
    + "</dl></div>"
  );
}

map.on("click", LAYER, (ev) => {
  const f = ev.features?.[0];
  if (!f) return;
  new maplibregl.Popup({ closeButton: true, maxWidth: "260px" })
    .setLngLat((f.geometry as GeoPoint).coordinates as [number, number])
    .setHTML(popupHtml(f.properties as Record<string, unknown>))
    .addTo(map);
});
map.on("mouseenter", LAYER, () => { map.getCanvas().style.cursor = "pointer"; });
map.on("mouseleave", LAYER, () => { map.getCanvas().style.cursor = ""; });

/** サーバーを呼び直す。会話には戻らず、同じツールをビューから呼ぶ */
async function recall(patch: Record<string, unknown>): Promise<void> {
  if (!state) return;
  mainEl.classList.add("busy");
  for (const b of seikatsuButtons) b.disabled = true;
  fatalEl.disabled = true;
  try {
    apply(await app.callServerTool({ name: "accident_map", arguments: { ...state.args, ...patch } }));
  } catch (e) {
    errEl.textContent = "再集計に失敗した: " + (e instanceof Error ? e.message : String(e));
    errEl.hidden = false;
    mainEl.classList.remove("busy");
    for (const b of seikatsuButtons) b.disabled = false;
    fatalEl.disabled = false;
  }
}

for (const b of seikatsuButtons) {
  b.addEventListener("click", () => {
    const v = b.dataset.seikatsu === "none" ? null : b.dataset.seikatsu;
    if (!state || (state.args.seikatsu ?? null) === v) return;
    void recall({ seikatsu: v });
  });
}
fatalEl.addEventListener("change", () => void recall({ fatal_only: fatalEl.checked }));

expandEl.addEventListener("click", async () => {
  const next = displayMode === "fullscreen" ? "inline" : "fullscreen";
  setDisplayMode((await app.requestDisplayMode({ mode: next })).mode);
});

function setDisplayMode(mode: string): void {
  displayMode = mode;
  mainEl.classList.toggle("fullscreen", mode === "fullscreen");
  expandEl.textContent = mode === "fullscreen" ? "縮小" : "全画面";
  map.resize();
}

function handleHostContextChanged(ctx: McpUiHostContext): void {
  if (ctx.styles?.variables) applyHostStyleVariables(ctx.styles.variables);
  if (ctx.styles?.css?.fonts) applyHostFonts(ctx.styles.css.fonts);
  if (ctx.safeAreaInsets) {
    const { top, right, bottom, left } = ctx.safeAreaInsets;
    mainEl.style.padding = `${top + 14}px ${right + 14}px ${bottom + 14}px ${left + 14}px`;
  }
  if (ctx.availableDisplayModes?.includes("fullscreen")) expandEl.hidden = false;
  if (ctx.displayMode) setDisplayMode(ctx.displayMode);

  if (ctx.theme) {
    applyDocumentTheme(ctx.theme);
    const next = ctx.theme === "dark" ? "dark" : "light";
    if (next !== theme) {
      theme = next;
      // 背景を差し替えると点のレイヤーも消える。落ち着いてから貼り直す
      map.setStyle(basemapStyle(theme), { diff: false });
      map.once("idle", addLayers);
    }
  }
}

// 1. App を作る
const app = new App({ name: "npa-accident-map", version: "1.0.0" });

// 2. ハンドラは connect() の前に全部登録する
app.ontoolresult = apply;
app.ontoolinput = () => { mainEl.classList.add("busy"); };
app.ontoolcancelled = (params) => {
  errEl.textContent = "集計が中断された: " + params.reason;
  errEl.hidden = false;
  mainEl.classList.remove("busy");
};
app.onhostcontextchanged = handleHostContextChanged;
app.onteardown = async () => ({});
app.onerror = (e) => console.error("[accident-map]", e);

// 3. 接続
app.connect().then(() => {
  const ctx = app.getHostContext();
  if (ctx) handleHostContextChanged(ctx);
});
