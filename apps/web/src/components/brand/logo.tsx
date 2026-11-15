import { cn } from "@/lib/utils";

/**
 * Sahaj logo: "voice bars" (docs/design/logo-1c). Shapes and proportions are exactly the design's;
 * only the colours are mapped to our tokens:
 *   design primary #1846C4 → --brand-action · sky #38B6F5 → --brand-cyan · navy #0B1B3F → --brand-navy
 * The third bar is always the accent (cyan).
 */

type Bars = { w: number; gap: number; heights: number[] };

/** Geometry from the design file, in its own units. */
const ICON: Bars & { size: number } = { size: 512, w: 50, gap: 30, heights: [116, 238, 170, 82] };
const LOCKUP: Bars = { w: 14, gap: 8, heights: [30, 62, 44, 22] };

function bars({ w, gap, heights }: Bars, cx: number, cy: number, fills: string[]) {
  const total = heights.length * w + (heights.length - 1) * gap;
  return heights.map((h, i) => (
    <rect key={i} x={cx - total / 2 + i * (w + gap)} y={cy - h / 2} width={w} height={h} rx={w / 2} fill={fills[i]} />
  ));
}

/** The round app icon: brand circle with white bars and the cyan accent bar. */
export function LogoMark({ size = 34, className }: { size?: number; className?: string }) {
  const s = ICON.size;
  return (
    <svg aria-hidden width={size} height={size} viewBox={`0 0 ${s} ${s}`} className={cn("flex-none", className)}>
      <circle cx={s / 2} cy={s / 2} r={s / 2} fill="var(--brand-action)" />
      {bars(ICON, s / 2, s / 2, ["#fff", "#fff", "var(--brand-cyan)", "#fff"])}
    </svg>
  );
}

/**
 * The bars on their own (lockup symbol). `tone="auto"` follows the theme like the design's two lockups:
 * brand bars on light, white bars on dark. `tone="inverse"` is white bars for brand-coloured backgrounds.
 */
export function LogoBars({ height = 31, tone = "auto", className }: {
  height?: number; tone?: "auto" | "inverse"; className?: string;
}) {
  const total = LOCKUP.heights.length * LOCKUP.w + (LOCKUP.heights.length - 1) * LOCKUP.gap;
  const maxH = Math.max(...LOCKUP.heights);
  const bar = tone === "inverse" ? "#fff" : "var(--logo-bar)";
  return (
    <svg aria-hidden height={height} viewBox={`0 0 ${total} ${maxH}`} className={cn("flex-none", className)}
      style={{ width: (height * total) / maxH }}>
      {bars(LOCKUP, total / 2, maxH / 2, [bar, bar, "var(--brand-cyan)", bar])}
    </svg>
  );
}

/**
 * Bars + "Sahaj" wordmark, as in the design's lockups (Anek Latin Bold, −0.025em). In the design the symbol is
 * 62/88 of the type size and sits 22/88 of it away from the word.
 */
export function LogoLockup({ size = 32, tone = "auto", className }: {
  size?: number; tone?: "auto" | "inverse"; className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center", className)} style={{ gap: size * (22 / 88) }} aria-label="Sahaj" role="img">
      <LogoBars height={size * (62 / 88)} tone={tone} />
      <span aria-hidden className="font-bold leading-none"
        style={{ fontSize: size, letterSpacing: "-0.025em", color: tone === "inverse" ? "#fff" : "var(--logo-word)" }}>
        Sahaj
      </span>
    </span>
  );
}
