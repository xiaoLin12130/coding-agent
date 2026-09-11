import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const BACKEND = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    // 5173 is already used by another local project's dev server on this
    // machine, so the console owns a dedicated port instead.
    host: "127.0.0.1",
    port: 5273,
    strictPort: true,
    // The browser talks to one origin; Vite forwards /api and /ws to FastAPI.
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/ws": { target: BACKEND, ws: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
