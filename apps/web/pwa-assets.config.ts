import { defineConfig, minimal2023Preset } from "@vite-pwa/assets-generator/config";

// Generates favicon, apple-touch-icon and maskable PWA icons from public/icon.svg at build time.
// Swap icon.svg for the final logo from the design.
export default defineConfig({
  headLinkOptions: { preset: "2023" },
  preset: {
    ...minimal2023Preset,
    maskable: { ...minimal2023Preset.maskable, resizeOptions: { background: "#0f3d3e" } },
    apple: { ...minimal2023Preset.apple, resizeOptions: { background: "#0f3d3e" } },
  },
  images: ["public/icon.svg"],
});
