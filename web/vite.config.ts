import { defineConfig } from "vite";

// 本番は Worker が web/dist を静的アセットとして配り、/web/mcp をコンテナへ通す。
// 手元では `python mcp_server/server.py --http --port 8000` を立て、/web/mcp をそこへ向ける。
export default defineConfig({
  server: {
    proxy: {
      "/web/mcp": {
        target: process.env.MCP_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: () => "/mcp",
      },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
