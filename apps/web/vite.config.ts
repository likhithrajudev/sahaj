import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = process.env.SAHAJ_API ?? "http://localhost:8000";

export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: {
    port: 5173,
    // everything outside /app goes to the API, WebSockets included
    proxy: { "^/(?!app).*": { target: api, changeOrigin: true, ws: true } },
  },
});
