/**
 * @file 背景地図のスタイル（地理院 最適化ベクトルタイル・淡色地図風）。
 *
 * スタイルJSONは shiwaku/dm-converter の viewer/public/pale.json をそのまま取り込んだもの
 * （`src/gsi-pale.json`）。iframe は外部ファイルを取りに行けないので、バンドルに含める。
 *
 * ダーク化の明度反転は同リポジトリ viewer/src/basemap.ts の手法を踏襲した。
 * 色を個別に指定し直すより、ホストのテーマ切り替えに追随させるほうが破綻が少ない。
 */
import type { StyleSpecification } from "maplibre-gl";
import paleStyle from "./gsi-pale.json";

/**
 * 素のスタイルは PMTiles を指しているが、pmtiles プロトコルを足すとバンドルが増える。
 * 同じタイルは XYZ でも配信されているので、そちらに向け直す。
 */
const XYZ = "https://cyberjapandata.gsi.go.jp/xyz/optimal_bvmap-v1/{z}/{x}/{y}.pbf";

type Rgba = [number, number, number, number];

function parseColor(str: string): Rgba | null {
  const rgba = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$/i.exec(str.trim());
  if (rgba) return [+rgba[1], +rgba[2], +rgba[3], rgba[4] !== undefined ? +rgba[4] : 1];
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(str.trim());
  if (!hex) return null;
  const h = hex[1].length === 3 ? hex[1].split("").map((c) => c + c).join("") : hex[1];
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16), 1];
}

function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h / 6, s, l];
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  if (s === 0) { const v = Math.round(l * 255); return [v, v, v]; }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const hue = (t: number): number => {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  return [Math.round(hue(h + 1 / 3) * 255), Math.round(hue(h) * 255), Math.round(hue(h - 1 / 3) * 255)];
}

/** 明度を反転して暗くする。色相は残し、彩度は少し抑える。 */
function darken(str: string): string {
  const c = parseColor(str);
  if (!c) return str;
  const [h, s, l] = rgbToHsl(c[0], c[1], c[2]);
  const [r, g, b] = hslToRgb(h, s * 0.85, Math.min(0.9, Math.max(0.05, 1 - l)));
  return `rgba(${r},${g},${b},${c[3]})`;
}

/** paint 値は式（配列）にもなるので、色文字列だけを再帰的に置き換える。 */
function mapColors(v: unknown): unknown {
  if (typeof v === "string") return parseColor(v) ? darken(v) : v;
  if (Array.isArray(v)) return v.map(mapColors);
  return v;
}

/**
 * 背景地図のスタイルを返す。dark のときは色を明度反転する。
 * 反転は 123 レイヤーぶん走るので、テーマごとに1回だけ作ってキャッシュする。
 */
const cache = new Map<string, StyleSpecification>();

export function basemapStyle(theme: "light" | "dark"): StyleSpecification {
  const hit = cache.get(theme);
  if (hit) return hit;

  const style = structuredClone(paleStyle) as unknown as StyleSpecification;
  const src = style.sources.v as { tiles?: string[]; minzoom?: number };
  src.tiles = [XYZ];
  src.minzoom = 4; // XYZ配信は z4 から。0 のままだと存在しないタイルを取りに行く

  if (theme === "dark") {
    for (const layer of style.layers) {
      const paint = (layer as { paint?: Record<string, unknown> }).paint;
      if (!paint) continue;
      for (const key of Object.keys(paint)) {
        if (key.includes("color")) paint[key] = mapColors(paint[key]);
      }
    }
  }
  cache.set(theme, style);
  return style;
}
