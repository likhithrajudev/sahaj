import { registerSW } from "virtual:pwa-register";

/** Registers the service worker (production builds only). New versions activate on the next launch. */
export function registerPWA() {
  if (import.meta.env.DEV) return;
  registerSW({ immediate: true });
}

/** Android/desktop Chrome install prompt, captured so the UI can offer "Install app" at the right moment. */
type InstallPrompt = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };
let deferred: InstallPrompt | null = null;
const listeners = new Set<() => void>();

window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferred = e as InstallPrompt;
  listeners.forEach((l) => l());
});

export const pwa = {
  /** Running as an installed app (home screen). */
  isStandalone: () =>
    window.matchMedia("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true,
  /** iOS has no install prompt: show "Share → Add to Home Screen" instructions instead. */
  isIOS: () => /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1),
  canPrompt: () => deferred !== null,
  async prompt() {
    if (!deferred) return false;
    await deferred.prompt();
    const { outcome } = await deferred.userChoice;
    deferred = null;
    return outcome === "accepted";
  },
  onChange(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};
