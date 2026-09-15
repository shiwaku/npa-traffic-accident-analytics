import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// vite-plugin-singlefile が JS/CSS を1枚のHTMLに畳み込む。
// サンドボックスiframeは外部アセットを取りに行けないので、これは必須。
//
// ビューは2つあり、1回のビルドでは1枚しか畳み込めない（単一HTML化は
// エントリが1つであることが前提）。`--mode map` で切り替えて2回走らせる。
export default defineConfig(({ mode }) => {
  const isMap = mode === "map";
  return {
    plugins: [viteSingleFile()],
    build: {
      outDir: "dist",
      // 2回目で1回目の成果物を消さないこと
      emptyOutDir: !isMap,
      // MapLibre が大きい。畳み込む以上サイズ警告は意味がないので黙らせる
      chunkSizeWarningLimit: 4096,
      rollupOptions: { input: isMap ? "map-app.html" : "mcp-app.html" },
    },
  };
});
