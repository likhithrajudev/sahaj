import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type ProxyOptions } from "vite";
import { VitePWA } from "vite-plugin-pwa";

/** First path segments that belong to the API (keep in sync with API_PREFIXES in apps/api/main.py). */
const API_PATHS = ["ws", "auth", "users", "admin", "chat", "consents", "files", "feedback", "usage", "desk", "stt",
  "audit", "ready", "metrics", "health", "docs", "redoc", "openapi.json", "test", "app",
  "calculators", "financial", "platform", "search", "inbox"];

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // FastAPI in development. The app always calls same-origin paths, so the phone only needs to reach Vite.
  const api = env.SAHAJ_API_URL ?? "http://127.0.0.1:8000";
  // Every API path (apps/api/main.py API_PREFIXES) goes to FastAPI; everything else is the app.
  const proxy: Record<string, ProxyOptions> = Object.fromEntries(
    API_PATHS.map((p) => [`/${p}`, { target: api, changeOrigin: true, ws: p === "ws" }]),
  );
  // Tunnels used for iPhone testing (the mic needs HTTPS). Add more with SAHAJ_ALLOWED_HOSTS=a.com,b.com
  const allowedHosts = [".ngrok-free.app", ".ngrok.app", ".ngrok.io", ".trycloudflare.com", ".loca.lt",
    ...(env.SAHAJ_ALLOWED_HOSTS ?? "").split(",").filter(Boolean)];

  return {
    plugins: [
      react(),
      tailwindcss(),
      VitePWA({
        registerType: "autoUpdate",
        injectRegister: false, // registered in src/pwa.ts
        manifest: {
          name: "Sahaj",
          short_name: "Sahaj",
          description: "Insurance and loans, explained in your language",
          lang: "en-IN",
          start_url: "/",
          scope: "/",
          display: "standalone",
          orientation: "portrait",
          background_color: "#004299", // the splash colour while the app starts
          theme_color: "#F5F5F5",
          // Rendered from the logo's geometry (docs/design/logo-1c) in the brand token colours
          icons: [
            { src: "pwa-64x64.png", sizes: "64x64", type: "image/png" },
            { src: "pwa-192x192.png", sizes: "192x192", type: "image/png" },
            { src: "pwa-512x512.png", sizes: "512x512", type: "image/png" },
            { src: "maskable-icon-512x512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
          ],
        },
        workbox: {
          globPatterns: ["**/*.{js,css,html,svg,png,ico,webmanifest}", "**/material-symbols-*.woff2"], // icons work offline
          // Never serve the API, the socket or the old test page from the app shell.
          navigateFallbackDenylist: [new RegExp(`^/(${API_PATHS.join("|").replace(".", "\\.")})(/|$)`)],
          runtimeCaching: [
            {
              // Indic fonts are loaded only when a script appears (unicode-range), then kept offline.
              urlPattern: ({ url }) => url.pathname.endsWith(".woff2"),
              handler: "CacheFirst",
              options: { cacheName: "fonts", expiration: { maxEntries: 60, maxAgeSeconds: 60 * 60 * 24 * 365 } },
            },
          ],
        },
        devOptions: { enabled: false },
      }),
    ],
    resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
    server: { host: true, port: 5173, proxy, allowedHosts },
    preview: { host: true, port: 4173, proxy, allowedHosts },
  };
});
