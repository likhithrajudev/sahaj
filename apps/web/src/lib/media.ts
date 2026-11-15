import { useSyncExternalStore } from "react";

const DESKTOP = "(min-width: 1024px)";

/** Desktop layout: side panel for cards, floating dock. */
export function useIsDesktop(): boolean {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(DESKTOP);
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => window.matchMedia(DESKTOP).matches,
    () => false,
  );
}
