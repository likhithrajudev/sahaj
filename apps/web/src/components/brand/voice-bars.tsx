import { useReducedMotion } from "motion/react";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { useSession } from "@/store/session";

/** The logo's four bars (docs/design/logo-1c): heights as a share of the tallest, width and gap per unit of height. */
const SHAPE = [116, 238, 170, 82].map((h) => h / 238);
const WIDTH = 14 / 62;
const GAP = 8 / 62;
/** How strongly each bar answers the voice: the tall middle bars lead, the short outer ones follow. */
const GAIN = [0.75, 1, 0.9, 0.6];

export type VoiceMode = "still" | "listening" | "thinking" | "speaking";

/**
 * The logo's voice bars, alive: the same shape in every state, so the brand mark is what listens, thinks and speaks.
 * listening follows the microphone level, speaking moves like speech, thinking ripples left to right.
 */
export function VoiceBars({ mode, height = 28, tone = "brand", className }: {
  mode: VoiceMode; height?: number; tone?: "brand" | "inverse" | "muted"; className?: string;
}) {
  const reduce = useReducedMotion();
  const bars = useRef<(HTMLSpanElement | null)[]>([]);

  useEffect(() => {
    if (mode !== "listening" && mode !== "speaking") return;
    const current = [...SHAPE];
    let frame = 0;
    const tick = () => {
      const t = performance.now() / 1000;
      const level = useSession.getState().level;
      current.forEach((value, i) => {
        let target: number;
        if (mode === "listening") {
          const wobble = reduce ? 0 : 0.05 * Math.sin(t * 9 + i * 1.7);
          target = 0.2 + Math.min(1, level * 1.8) * GAIN[i] * 0.8 + wobble;
        } else {
          target = reduce ? SHAPE[i]
            : 0.5 + 0.28 * Math.sin(t * 5.1 + i * 1.3) * Math.sin(t * 2.3 + i) + 0.18 * Math.sin(t * 11 + i * 2.1);
        }
        current[i] = value + (Math.min(1, Math.max(0.18, target)) - value) * 0.3;
        const el = bars.current[i];
        if (el) el.style.height = `${current[i] * 100}%`;
      });
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      bars.current.forEach((el, i) => { if (el) el.style.height = `${SHAPE[i] * 100}%`; });
    };
  }, [mode, reduce]);

  const fill = tone === "inverse" ? "#fff" : tone === "muted" ? "var(--ink-3)" : "var(--logo-bar)";
  return (
    <span aria-hidden className={cn("inline-flex flex-none items-center", className)}
      style={{ height, gap: height * GAP }}>
      {SHAPE.map((h, i) => (
        <span key={i} ref={(el) => { bars.current[i] = el; }}
          className={cn("block rounded-full", mode === "thinking" && "bar-ripple")}
          style={{
            width: Math.max(3, height * WIDTH),
            height: `${h * 100}%`,
            background: i === 2 && tone !== "muted" ? "var(--brand-cyan)" : fill,
            animationDelay: mode === "thinking" ? `${i * 0.14}s` : undefined,
            transition: mode === "still" ? "height 320ms cubic-bezier(0.16, 1, 0.3, 1)" : undefined,
          }} />
      ))}
    </span>
  );
}
