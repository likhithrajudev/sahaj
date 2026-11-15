import { cn } from "@/lib/utils";

/** The स mark with the cyan dot. `inverse` = white tile with a blue letter (splash). */
export function LogoMark({ size = 34, inverse = false, className }: { size?: number; inverse?: boolean; className?: string }) {
  const dot = Math.round(size * 0.2);
  return (
    <div
      aria-hidden
      className={cn("relative flex flex-none items-center justify-center font-semibold leading-none", className)}
      style={{
        width: size, height: size, borderRadius: Math.round(size * 0.3),
        background: inverse ? "#fff" : "var(--mark)", color: inverse ? "var(--brand-action)" : "#fff",
        fontFamily: "'Anek Devanagari Variable', sans-serif", fontSize: Math.round(size * 0.62),
      }}
    >
      स
      <span className="absolute rounded-full bg-accent"
        style={{ width: dot, height: dot, right: Math.round(size * 0.15), top: Math.round(size * 0.15) }} />
    </div>
  );
}
