import { MAX_RECORDING_SECONDS } from "@sahaj/contracts";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { VoiceBars } from "@/components/brand/voice-bars";
import { Icon } from "@/components/ui/icon";
import { isStringKey, useT, type StringKey } from "@/lib/i18n";
import {
  cancelTalking, dismissDockError, replay, requestHuman, startTalking, stopSpeaking, stopTalking, toggleMute,
} from "@/lib/session";
import { cn } from "@/lib/utils";
import { canTalk, lastSpoken, useSession, withPerson, type SessionState } from "@/store/session";
import { openSheet } from "@/store/ui";

type DockState =
  | "idle" | "recording" | "sending" | "thinking" | "speaking" | "error" | "textonly"
  | "disabled" | "person" | "offline" | "blocked" | "budget";

function dockState(s: SessionState): DockState {
  if (s.connection === "offline") return "offline";
  if (s.budget.exceededUntil) return "budget";
  if (s.turn === "starting" || s.turn === "recording") return "recording";
  if (s.turn === "sending") return "sending";
  if (s.turn === "thinking") return "thinking";
  if (s.turn === "speaking") return "speaking";
  if (s.micError === "denied" || s.micError === "insecure" || s.micError === "unsupported") return "blocked";
  if (!canTalk(s)) return "disabled";
  if (s.dockError) return "error";
  if (withPerson(s)) return "person"; // talking goes to the person handling the case
  if (s.lastTextOnly) return "textonly";
  return "idle";
}

const SLIDE_TO_CANCEL_PX = 90;

export function Dock() {
  const t = useT();
  const state = useSession(dockState);
  const status = useSession((s) => s.status);
  const dockError = useSession((s) => s.dockError);
  const muted = useSession((s) => s.muted);
  const spoken = useSession(lastSpoken);
  const reduceMotion = useReducedMotion();
  const pointer = useRef<{ x: number; cancelled: boolean } | null>(null);
  const [dragX, setDragX] = useState(0);

  useSpaceToTalk();

  const person = useSession(withPerson);
  const off = state === "budget" || state === "offline" || state === "blocked" || state === "disabled";
  const label = ({
    idle: t("hold"), error: t("hold"), textonly: t("hold"), recording: t("release"), sending: t("sending"),
    thinking: status ? t(`step_${status}` as StringKey) : t("thinking"), speaking: t("tapStop"),
    person: t("holdToPerson"), offline: t("youreOffline"), blocked: t("micBlocked"), disabled: t("pleaseWait"),
    budget: t("budgetExceeded"),
  } satisfies Record<DockState, string>)[state];

  const onDown = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (state === "speaking") return stopSpeaking();
    if (state === "blocked") return openSheet("mic");
    if (off || state === "sending" || state === "thinking") return;
    e.currentTarget.setPointerCapture(e.pointerId); // keep receiving pointerup even if the finger drifts
    pointer.current = { x: e.clientX, cancelled: false };
    void startTalking();
  };
  const onMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const p = pointer.current;
    if (!p || p.cancelled) return;
    const dx = Math.min(0, e.clientX - p.x);
    setDragX(dx);
    if (dx < -SLIDE_TO_CANCEL_PX) {
      p.cancelled = true;
      setDragX(0);
      void cancelTalking();
    }
  };
  const onUp = () => {
    const p = pointer.current;
    pointer.current = null;
    setDragX(0);
    if (p && !p.cancelled) void stopTalking();
  };

  const talkButton = (
    <motion.button
      type="button"
      aria-label={label}
      aria-disabled={off || state === "thinking" || state === "sending"}
      className="no-callout group relative flex size-24 items-center justify-center rounded-full outline-offset-4"
      style={{ x: dragX }}
      onContextMenu={(e) => e.preventDefault()}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerCancel={() => { pointer.current = null; setDragX(0); void cancelTalking(); }}
    >
      <TalkFace state={state} reduceMotion={!!reduceMotion} />
    </motion.button>
  );

  const human = <SideAction icon="support_agent" label={t("human")} onClick={requestHuman} disabled={person} />;

  const right = state === "speaking" ? (
    <SideAction icon={muted ? "volume_up" : "volume_off"} label={muted ? t("unmute") : t("mute")} onClick={toggleMute} pressed={muted} />
  ) : spoken?.audioUrl && (state === "idle" || state === "error" || state === "person") ? (
    <SideAction icon="replay" label={t("replay")} onClick={() => replay(spoken.audioUrl!)} />
  ) : <span className="w-[88px]" />;

  return (
    <>
      {/* phone and tablet: the docked sheet */}
      <section aria-label={`Voice controls: ${label}`}
        className="pb-safe z-20 flex flex-none flex-col gap-2.5 rounded-t-[28px] border-t border-line bg-surface px-4 pt-3.5 shadow-dock lg:hidden">
        <DockStrip state={state} dockError={dockError} />
        <div className="grid grid-cols-[1fr_auto_1fr] items-start gap-2">
          <div className="justify-self-start">{human}</div>
          <div className="flex min-w-[150px] flex-col items-center gap-2">
            {talkButton}
            <motion.span key={label} aria-live="polite"
              initial={reduceMotion ? false : { opacity: 0, y: 3 }} animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
              className={cn("max-w-[190px] text-center text-[15px] font-semibold leading-[18px]",
                off || state === "thinking" || state === "sending" ? "text-ink-2" : "text-ink")}>
              {label}
            </motion.span>
          </div>
          <div className="justify-self-end">{right}</div>
        </div>
      </section>

      {/* desktop: a floating bar under the conversation column */}
      <section aria-label={`Voice controls: ${label}`} className="hidden px-6 pb-6 lg:block">
        <div className="mx-auto flex max-w-[680px] flex-col gap-2">
          <DockStrip state={state} dockError={dockError} />
          <div className="flex items-center gap-3 rounded-full bg-surface py-2 pl-7 pr-2 shadow-raised">
            <div className="flex min-w-0 flex-1 flex-col">
              <span className="text-[17px] font-semibold leading-6" aria-live="polite">
                {state === "idle" || state === "error" || state === "textonly" ? t("spaceHint") : label}
              </span>
              <span className="truncate text-[13px] text-ink-3">{t("spaceSub")}</span>
            </div>
            {spoken?.audioUrl && (state === "idle" || state === "error") && (
              <PillAction icon="replay" onClick={() => replay(spoken.audioUrl!)}>{t("replay")}</PillAction>
            )}
            {state === "speaking" && (
              <PillAction icon={muted ? "volume_up" : "volume_off"} onClick={toggleMute}>{muted ? t("unmute") : t("mute")}</PillAction>
            )}
            <PillAction icon="support_agent" onClick={requestHuman} disabled={person}>{t("human")}</PillAction>
            <div className="-my-3 scale-[0.8]">{talkButton}</div>
          </div>
        </div>
      </section>
    </>
  );
}

function SideAction({ icon, label, onClick, disabled, pressed }: {
  icon: string; label: string; onClick: () => void; disabled?: boolean; pressed?: boolean;
}) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} aria-pressed={pressed}
      className="group flex w-[88px] flex-col items-center gap-1.5 pt-3 disabled:opacity-50">
      <span className="flex size-[52px] items-center justify-center rounded-full bg-surface-2 text-primary transition-[transform,background-color] duration-150 group-hover:bg-primary-soft group-active:scale-95">
        <Icon name={icon} />
      </span>
      <span className="text-center text-[13px] font-semibold leading-4 text-ink-2">{label}</span>
    </button>
  );
}

function PillAction({ icon, onClick, disabled, children }: { icon: string; onClick: () => void; disabled?: boolean; children: string }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
      className="flex h-12 items-center gap-2 rounded-full bg-primary-soft px-4 font-semibold text-primary transition-[filter,transform] duration-150 hover:brightness-95 active:scale-[0.97] disabled:opacity-50">
      <Icon name={icon} size={20} /> {children}
    </button>
  );
}

/** Around the talk button while recording: fills over the 30 s limit, amber for the last five seconds. */
function LimitRing() {
  const since = useSession((s) => s.recordingSince);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(id);
  }, []);
  const elapsed = since ? Math.min(MAX_RECORDING_SECONDS, (now - since) / 1000) : 0;
  const warn = since !== null && MAX_RECORDING_SECONDS - elapsed <= 5;
  const r = 46;
  const c = 2 * Math.PI * r;
  return (
    <svg aria-hidden viewBox="0 0 96 96" className="pointer-events-none absolute inset-0 -rotate-90">
      <circle cx="48" cy="48" r={r} fill="none" stroke="var(--talk-ring)" strokeWidth="3" />
      <circle cx="48" cy="48" r={r} fill="none" strokeWidth="3" strokeLinecap="round"
        stroke={warn ? "var(--warn)" : "var(--talk)"} strokeDasharray={c}
        strokeDashoffset={c * (1 - elapsed / MAX_RECORDING_SECONDS)}
        style={{ transition: "stroke-dashoffset 100ms linear, stroke 200ms" }} />
    </svg>
  );
}

/** The circle inside the talk button, per state. The logo's bars listen, think and speak. */
function TalkFace({ state, reduceMotion }: { state: DockState; reduceMotion: boolean }) {
  const level = useSession((s) => s.level);
  switch (state) {
    case "recording":
      return (
        <>
          <motion.span aria-hidden className="absolute inset-1 rounded-full bg-talk-ring"
            animate={{ scale: reduceMotion ? 1 : 1 + Math.min(level, 1) * 0.3 }}
            transition={{ duration: 0.12, ease: "easeOut" }} />
          <LimitRing />
          <motion.span className="relative flex size-[78px] items-center justify-center rounded-full bg-talk shadow-talk"
            initial={reduceMotion ? false : { scale: 0.92 }} animate={{ scale: 1 }}
            transition={{ type: "spring", stiffness: 520, damping: 26 }}>
            <VoiceBars mode="listening" height={34} tone="inverse" />
          </motion.span>
        </>
      );
    case "sending":
      return (
        <span className="relative flex size-[76px] items-center justify-center rounded-full bg-surface-2 text-ink-2">
          <span className="absolute inset-0 animate-spin rounded-full border-[3px] border-line border-t-talk" />
          <Icon name="arrow_upward" size={30} />
        </span>
      );
    case "thinking":
      return (
        <span className="flex size-[76px] items-center justify-center rounded-full bg-surface-2">
          <VoiceBars mode="thinking" height={30} />
        </span>
      );
    case "speaking":
      return (
        <span className="relative flex size-[78px] items-center justify-center rounded-full bg-talk shadow-talk">
          <VoiceBars mode="speaking" height={32} tone="inverse" />
          <span className="absolute -bottom-0.5 -right-0.5 flex size-7 items-center justify-center rounded-full bg-surface text-primary shadow-card">
            <Icon name="stop" size={16} fill />
          </span>
        </span>
      );
    case "budget":
    case "offline":
    case "blocked":
    case "disabled":
      return (
        <span className="flex size-[76px] items-center justify-center rounded-full border-[1.5px] border-dashed border-control-line bg-surface-2 text-ink-3">
          <Icon name="mic_off" size={32} />
        </span>
      );
    default:
      return (
        <span className="flex size-[78px] items-center justify-center rounded-full bg-talk text-white shadow-talk transition-transform duration-150 ease-out group-hover:scale-[1.04]">
          <Icon name="mic" size={36} fill />
        </span>
      );
  }
}

/** The strip above the controls: recording timer, speaking progress, error, or text-only note. */
function DockStrip({ state, dockError }: { state: DockState; dockError: StringKey | string | null }) {
  const t = useT();
  const resets = useSession((s) => s.budget.exceededUntil);
  if (state === "recording") return <RecordingStrip />;
  if (state === "budget" && resets) {
    return (
      <div role="alert" className="flex min-h-12 items-center gap-2.5 rounded-2xl bg-warn-soft px-3.5 py-2 text-[15px] font-medium text-warm-ink">
        <Icon name="info" size={20} />
        <span>{t("budgetExceeded")} {t("budgetResets", { date: new Date(resets).toLocaleDateString(undefined, { day: "numeric", month: "long" }) })}</span>
      </div>
    );
  }
  if (state === "speaking") return <SpeakingStrip />;
  if (state === "error" && dockError) {
    return (
      <div role="alert" className="flex min-h-12 items-center gap-2.5 rounded-2xl bg-error-soft py-1.5 pl-3.5 pr-1.5 text-[15px] font-medium text-error-ink">
        <Icon name="hearing_disabled" size={20} />
        <span className="flex-1">{isStringKey(dockError) ? t(dockError) : dockError}</span>
        <button type="button" onClick={dismissDockError}
          className="flex h-9 items-center rounded-xl bg-surface px-3.5 text-sm font-semibold shadow-card">
          {t("tryAgain")}
        </button>
      </div>
    );
  }
  if (state === "textonly") {
    return (
      <div className="flex h-8 items-center gap-1.5 self-center rounded-full bg-info-soft px-3.5 text-[13px] font-semibold text-info">
        <Icon name="subtitles" size={17} /> {t("textOnly")}
      </div>
    );
  }
  return null;
}

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function RecordingStrip() {
  const t = useT();
  const since = useSession((s) => s.recordingSince);
  const [now, setNow] = useState(() => Date.now());
  const [bars, setBars] = useState<number[]>(() => Array(26).fill(4));
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, []);
  // rolling level history; if the browser gives no level, a gentle synthetic wave
  useEffect(() => {
    const id = setInterval(() => {
      setBars((b) => {
        const l = useSession.getState().level;
        const v = l > 0.01 ? l : reduceMotion ? 0.1 : 0.15 + Math.abs(Math.sin(Date.now() / 180)) * 0.35;
        return [...b.slice(1), Math.round(4 + v * 22)];
      });
    }, 80);
    return () => clearInterval(id);
  }, [reduceMotion]);

  const elapsed = since ? Math.min(MAX_RECORDING_SECONDS, (now - since) / 1000) : 0;
  const left = Math.max(0, Math.ceil(MAX_RECORDING_SECONDS - elapsed));
  const warn = left <= 5 && since !== null;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex h-12 items-center gap-3 rounded-2xl bg-primary-soft px-3.5">
        <span className="relative flex size-2.5 flex-none">
          <span className="ping-soft absolute inset-0 rounded-full bg-[#D93A2B]" />
          <span className="relative size-2.5 rounded-full bg-[#D93A2B]" />
        </span>
        <span className={cn("whitespace-nowrap text-base font-semibold tabular-nums", warn ? "text-warn" : "text-ink")}>
          {fmt(elapsed)} / 0:{MAX_RECORDING_SECONDS}
        </span>
        <div className="flex h-7 flex-1 items-center gap-[3px] overflow-hidden" aria-hidden>
          {bars.map((h, i) => (
            <span key={i} className="w-[3px] flex-none rounded-full bg-talk transition-[height] duration-75"
              style={{ height: h, opacity: 0.35 + (i / bars.length) * 0.65 }} />
          ))}
        </div>
        <span className="flex items-center whitespace-nowrap text-[13px] font-medium text-ink-2">
          <Icon name="chevron_right" size={18} className="nudge-left rotate-180" />{t("cancel")}
        </span>
      </div>
      {warn && <div className="text-center text-[13px] font-medium text-warn">{left} {t("warn")}</div>}
    </div>
  );
}

const SPEAK_BARS = Array.from({ length: 34 }, (_, i) => Math.round(4 + Math.abs(Math.sin(i * 1.3 + 4) * Math.cos(i * 0.4)) * 22));

function SpeakingStrip() {
  const speaking = useSession((s) => s.speaking);
  const progress = speaking && speaking.duration ? speaking.elapsed / speaking.duration : 0;
  return (
    <div className="flex h-12 items-center gap-3 rounded-2xl bg-primary-soft px-3.5">
      <VoiceBars mode="speaking" height={18} />
      <div className="flex h-7 flex-1 items-center gap-[3px] overflow-hidden" aria-hidden>
        {SPEAK_BARS.map((h, i) => (
          <span key={i} className="w-[3px] flex-none rounded-full bg-primary transition-opacity duration-300"
            style={{ height: h, opacity: i / SPEAK_BARS.length <= progress ? 1 : 0.28 }} />
        ))}
      </div>
      <span className="whitespace-nowrap text-[13px] font-semibold tabular-nums text-primary">
        {fmt(speaking?.elapsed ?? 0)} / {fmt(speaking?.duration ?? 0)}
      </span>
    </div>
  );
}

/** Desktop: hold Space to talk (ignored while typing in a field). */
function useSpaceToTalk() {
  useEffect(() => {
    const typing = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(el.tagName));
    };
    const down = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.repeat || typing(e)) return;
      e.preventDefault();
      void startTalking();
    };
    const up = (e: KeyboardEvent) => {
      if (e.code !== "Space" || typing(e)) return;
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
}
