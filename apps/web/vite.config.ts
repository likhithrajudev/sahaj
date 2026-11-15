import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type ProxyOptions } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // FastAPI in development. The app always calls same-origin paths, so the phone only needs to reach Vite.
  const api = env.SAHAJ_API_URL ?? "http://127.0.0.1:8000";
  const proxy: Record<string, ProxyOptions> = {
    "/ws": { target: api, ws: true, changeOrigin: true },
    "/stt": { target: api, changeOrigin: true },
    "/health": { target: api, changeOrigin: true },
    "/audit": { target: api, changeOrigin: true },
  };
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
        pwaAssets: { config: true, overrideManifestIcons: true },
        manifest: {
          name: "Sahaj",
          short_name: "Sahaj",
          description: "Insurance and loans, explained in your language",
          lang: "en-IN",
          start_url: "/",
          scope: "/",
          display: "standalone",
          orientation: "portrait",
          background_color: "#ffffff",
          theme_color: "#0f3d3e",
        },
        workbox: {
          globPatterns: ["**/*.{js,css,html,svg,png,ico,webmanifest}"],
          // Never serve the API, the socket or the old test page from the app shell.
          navigateFallbackDenylist: [/^\/(ws|stt|health|audit|docs|openapi\.json|redoc|test)(\/|$)/],
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
