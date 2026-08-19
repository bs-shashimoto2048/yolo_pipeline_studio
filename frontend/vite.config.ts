import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 開発時は /api を FastAPI(8000) にプロキシする
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true, // LAN上の他端末からもアクセスできるよう全インターフェースで待受
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
