import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, Vite serves the dashboard on :5173 and forwards API and
// WebSocket traffic to the FastAPI backend on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
