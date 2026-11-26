import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    // 同时监听 IPv4/IPv6：Windows 上 localhost 常先解析到 ::1，只绑 127.0.0.1 会连不上
    host: true,
    proxy: {
      // 用 127.0.0.1 而不是 localhost，避免代理走 ::1 打不到 uvicorn（uvicorn 默认只监听 127.0.0.1）
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
