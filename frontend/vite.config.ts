import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// port番号として有効な場合のみ採用し、それ以外（未指定・空文字・非数値・0・負数・
// 65536以上・小数・Infinity等）は安全にfallbackへ倒す（Issue #12）。
// 前後の空白付き整数（例: " 18080 "）はNumber()が自動でtrimするため有効値として扱われる。
function resolvePort(value: string | undefined, fallback: number): number {
  const n = Number(value);
  return Number.isInteger(n) && n >= 1 && n <= 65535 ? n : fallback;
}

// 開発時は /api を FastAPI にプロキシする。
// ポートは環境変数 VITE_DEV_PORT / VITE_BACKEND_PORT で上書き可能
// （他アプリとのポート衝突を避けたい場合に使用。未設定時は従来通り 5173 / 8000）。
export default defineConfig(({ mode }) => {
  // 対象の2変数は VITE_ prefixのため、prefixを絞って読み込む
  // （必要以上に全envを読み込まない）。
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const devPort = resolvePort(env.VITE_DEV_PORT, 5173);
  const backendPort = resolvePort(env.VITE_BACKEND_PORT, 8000);

  return {
    plugins: [react()],
    server: {
      port: devPort,
      host: true, // LAN上の他端末からもアクセスできるよう全インターフェースで待受
      proxy: {
        "/api": {
          target: `http://localhost:${backendPort}`,
          changeOrigin: true,
        },
      },
    },
  };
});
