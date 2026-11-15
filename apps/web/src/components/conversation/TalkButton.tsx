import { MAX_RECORDING_SECONDS } from "@sahaj/contracts";
import { Loader2, Mic, Square } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";
import { cancelTalking, startTalking, stopSpeaking, stopTalking } from "@/lib/session";
import { cn } from "@/lib/utils";
import { canTalk, useSession } from "@/store/session";

const LABEL = {
  idle: "Hold to talk",
  starting: "Opening mic…",
  recording: "Release to send",
  thinking: "Sahaj is thinking…",
  speaking: "Tap to stop",
} as const;

export function TalkButton() {
  const turn = useSession((s) => s.turn);
  const since = useSession((s) => s.recordingSince);
  const enabled = useSession(canTalk) || turn === "recording" || turn === "starting" || turn === "speaking";
  const reduceMotion = useReducedMotion();
  const elapsed = useElapsed(since);

  // Desktop: hold Space to talk
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.repeat || isTyping(e)) return;
      e.preventDefault();
      void startTalking();
    };
    const up = (e: KeyboardEvent) => {
      if (e.code !== "Space" || isTyping(e)) return;
      e.preventDefault();
      void stopTalking();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  const recording = turn === "recording";
  const nearLimit = recording && elapsed >= MAX_RECORDING_SECONDS - 5;

  return (
    <div className="flex flex-col items-center gap-2">
      <div className={cn("h-5 text-sm tabular-nums", nearLimit ? "text-destructive" : "text-muted-foreground")} aria-live="polite">
        {recording ? `0:${String(elapsed).padStart(2, "0")} / 0:${MAX_RECORDING_SECONDS}` : LABEL[turn]}
      </div>
      <motion.button
        type="button"
        aria-label={LABEL[turn]}
        disabled={!enabled}
        className={cn(
          "no-callout relative flex size-20 items-center justify-center rounded-full shadow-lg transition-colors",
          "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring/40 disabled:opacity-40",
          recording ? "bg-destructive text-white" : "bg-accent text-accent-foreground",
        )}
        animate={recording && !reduceMotion ? { scale: [1, 1.08, 1] } : { scale: 1 }}
        transition={recording ? { repeat: Infinity, duration: 1.2 } : { duration: 0.15 }}
        onContextMenu={(e) => e.preventDefault()}
        onPointerDown={(e) => {
          if (turn === "speaking") return stopSpeaking();
          e.currentTarget.setPointerCapture(e.pointerId); // keep receiving pointerup even if the finger drifts
          void startTalking();
        }}
        onPointerUp={() => void stopTalking()}
        onPointerCancel={() => void cancelTalking()}
      >
        {turn === "thinking" || turn === "starting" ? (
          <Loader2 className="size-8 animate-spin" />
        ) : turn === "speaking" ? (
          <Square className="size-7" />
        ) : (
          <Mic className="size-8" />
        )}
      </motion.button>
    </div>
  );
}

function useElapsed(since: number | null) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!since) return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [since]);
  return since ? Math.min(MAX_RECORDING_SECONDS, Math.floor((now - since) / 1000)) : 0;
}

const isTyping = (e: KeyboardEvent) => {
  const el = e.target as HTMLElement | null;
  return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
};
