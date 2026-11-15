import { useSyncExternalStore, type ReactNode } from "react";

// Voice-bars logo, geometry from apps/web/src/components/brand/logo.tsx (docs/design/logo-1c).
const LOCKUP = { w: 14, gap: 8, heights: [30, 62, 44, 22] };

export function LogoLockup({ size = 28, inverse = false }: { size?: number; inverse?: boolean }) {
  const { w, gap, heights } = LOCKUP;
  const total = heights.length * w + (heights.length - 1) * gap;
  const maxH = Math.max(...heights);
  const bar = inverse ? "#fff" : "var(--logo-bar)";
  const h = size * (62 / 88);
  return (
    <span role="img" aria-label="Sahaj" style={{ display: "inline-flex", alignItems: "center", gap: size * (22 / 88) }}>
      <svg aria-hidden height={h} width={(h * total) / maxH} viewBox={`0 0 ${total} ${maxH}`}>
        {heights.map((bh, i) => (
          <rect key={i} x={i * (w + gap)} y={(maxH - bh) / 2} width={w} height={bh} rx={w / 2}
            fill={i === 2 ? "var(--brand-cyan)" : bar} />
        ))}
      </svg>
      <span aria-hidden style={{ fontSize: size, fontWeight: 700, lineHeight: 1, letterSpacing: "-0.025em", color: inverse ? "#fff" : "var(--logo-word)" }}>
        Sahaj
      </span>
    </span>
  );
}

const PATHS: Record<string, ReactNode> = {
  chat: <path d="M4 5h16v11H8l-4 4z" />,
  voice: <><path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></>,
  doc: <><path d="M14 3H6v18h12V7z" /><path d="M14 3v4h4M9 13h6M9 17h6" /></>,
  bell: <><path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z" /><path d="M10 21h4" /></>,
  lock: <><rect x="5" y="10" width="14" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></>,
  chart: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
  headset: <><path d="M4 14v-2a8 8 0 0 1 16 0v2" /><rect x="3" y="14" width="4" height="6" rx="1.5" /><rect x="17" y="14" width="4" height="6" rx="1.5" /></>,
  grid: <><rect x="4" y="4" width="7" height="7" rx="1.5" /><rect x="13" y="4" width="7" height="7" rx="1.5" /><rect x="4" y="13" width="7" height="7" rx="1.5" /><rect x="13" y="13" width="7" height="7" rx="1.5" /></>,
  people: <><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6.5 6.5 0 0 1 3.5 6" /></>,
  megaphone: <><path d="M4 10v4h3l8 5V5L7 10z" /><path d="M18.5 9a4 4 0 0 1 0 6" /></>,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  shield: <><path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z" /><path d="M8.5 12l2.5 2.5 4.5-5" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  moon: <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" />,
  up: <><path d="M7 11v9H4v-9z" /><path d="M7 11l4-8a2 2 0 0 1 2 2v4h5.5a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.3 20H7" /></>,
  down: <><path d="M7 13V4H4v9z" /><path d="M7 13l4 8a2 2 0 0 0 2-2v-4h5.5a2 2 0 0 0 2-2.3l-1.2-7A2 2 0 0 0 17.3 4H7" /></>,
  out: <><path d="M14 4h5v16h-5" /><path d="M10 8l-4 4 4 4M6 12h10" /></>,
};

export function Icon({ name, size = 20 }: { name: keyof typeof PATHS; size?: number }) {
  return (
    <svg aria-hidden width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      {PATHS[name]}
    </svg>
  );
}

// Theme: follows the system unless the person picks one; stored per browser.
type Theme = "light" | "dark";
const media = window.matchMedia("(prefers-color-scheme: dark)");
const listeners = new Set<() => void>();
const read = (): Theme | null => {
  try { return (localStorage.getItem("sahaj.theme") as Theme | null) ?? null; } catch { return null; }
};
let chosen = read();
const current = (): Theme => chosen ?? (media.matches ? "dark" : "light");
function apply() {
  document.documentElement.dataset.theme = current();
  listeners.forEach((l) => l());
}
media.addEventListener("change", apply);
apply();

export function toggleTheme() {
  chosen = current() === "dark" ? "light" : "dark";
  try { localStorage.setItem("sahaj.theme", chosen); } catch { /* private mode */ }
  apply();
}

export function useTheme() {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, current);
}
