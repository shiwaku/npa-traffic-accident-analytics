import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// vite-plugin-singlefile が JS/CSS を1枚のHTMLに畳み込む。
// サンドボックスiframeは外部アセットを取りに行けないので、これは必須。
//
// ビューは3つあり、1回のビルドでは1枚しか畳み込めない（単一HTML化は
// エントリが1つであることが前提）。`--mode map` / `--mode table` で
// 切り替えて3回走らせる。
const ENTRY: Record<string, string> = {
  map: "map-app.html",
  table: "table-app.html",
};

export default defineConfig(({ mode }) => {
  const entry = ENTRY[mode];
  return {
    plugins: [viteSingleFile()],
    build: {
      outDir: "dist",
      // 2回目以降で前の成果物を消さないこと
      emptyOutDir: !entry,
      // MapLibre が大きい。畳み込む以上サイズ警告は意味がないので黙らせる
      chunkSizeWarningLimit: 4096,
      rollupOptions: { input: entry ?? "mcp-app.html" },
    },
  };
});
