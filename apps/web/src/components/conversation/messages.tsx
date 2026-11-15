import type { AgentName } from "@sahaj/contracts";
import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import { VoiceBars } from "@/components/brand/voice-bars";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { useT, type StringKey } from "@/lib/i18n";
import { rateReply, replay, requestHuman, sendSuggestion } from "@/lib/session";
import { cn } from "@/lib/utils";
import { canTalk, useSession, withPerson, type TimelineItem } from "@/store/session";
import { openSheet } from "@/store/ui";

/**
 * How items arrive. What the person said slides in from their side; what Sahaj says comes into focus, from a soft blur,
 * as if spoken into the room. Reduced motion keeps the fade only.
 */
export function Rise({ children, className, from = "sahaj" }: { children: ReactNode; className?: string; from?: "person" | "sahaj" }) {
  const reduce = useReducedMotion();
  const start = reduce ? { opacity: 0 }
    : from === "person" ? { opacity: 0, x: 14 }
    : { opacity: 0, y: 10, filter: "blur(6px)" };
  return (
    <motion.div className={className}
      initial={start}
      animate={{ opacity: 1, x: 0, y: 0, filter: "blur(0px)" }}
      transition={{ duration: from === "person" ? 0.26 : 0.42, ease: [0.16, 1, 0.3, 1] }}>
      {children}
    </motion.div>
  );
}

export function UserBubble({ text, children }: { text?: string; children?: ReactNode }) {
  return (
    <div dir="auto" className="ml-auto max-w-[85%] rounded-[22px] rounded-br-md px-4 py-3 text-[17px] leading-[25px] text-on-bubble shadow-card"
      style={{ background: "linear-gradient(150deg, color-mix(in srgb, var(--bubble) 88%, var(--brand-cyan)), var(--bubble) 60%)" }}>
      {children ?? text}
    </div>
  );
}

const AGENT: Record<AgentName, { icon: string; label: StringKey; tone: "insurance" | "loan" | "general" }> = {
  insurance: { icon: "health_and_safety", label: "agent_insurance", tone: "insurance" },
  advice: { icon: "health_and_safety", label: "agent_advice", tone: "insurance" },
  loan: { icon: "account_balance", label: "agent_loan", tone: "loan" },
  general: { icon: "chat_bubble", label: "agent_general", tone: "general" },
};

export function AgentBadge({ agent, question }: { agent: AgentName; question?: boolean }) {
  const t = useT();
  const a = AGENT[agent] ?? AGENT.general;
  return (
    <Badge tone={a.tone} icon={question ? "help" : a.icon}>
      {t(a.label)}{question && <> · {t("question")}</>}
    </Badge>
  );
}

type Assistant = Extract<TimelineItem, { kind: "assistant" }>;

export function AssistantBubble({ item, isLatest, children }: { item: Assistant; isLatest: boolean; children: ReactNode }) {
  const t = useT();
  const turn = useSession((s) => s.turn);
  const speakingThis = useSession((s) => s.turn === "speaking") && isLatest;

  if (item.fallback) return <FallbackBubble>{children}</FallbackBubble>;

  return (
    <div className="card max-w-[92%] rounded-tl-md px-4 pb-3.5 pt-3.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <AgentBadge agent={item.agent} question={item.replyKind === "ask" && item.agent !== "advice"} />
        <VerificationBadge item={item} />
      </div>
      <p dir="auto" className="mt-2.5 text-[17px] leading-[26px]">{children}</p>
      {item.textOnly && (
        <p className="mt-2 flex items-center gap-1.5 text-[13px] font-semibold text-info">
          <Icon name="subtitles" size={17} /> {t("textOnlyNoAudio")}
        </p>
      )}
      {isLatest && (item.audioUrl || item.replyKind !== "ask") && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line pt-2.5">
          <Feedback item={item} />
          {item.audioUrl && !speakingThis && (
            <button type="button" onClick={() => replay(item.audioUrl!)} disabled={turn !== "idle"}
              className="flex h-10 items-center gap-1.5 rounded-full bg-primary-soft px-3.5 text-[15px] font-semibold text-primary transition-[filter] hover:brightness-95 disabled:opacity-50">
              <Icon name="play_arrow" size={20} fill /> {t("replay")}
              {item.audioSeconds ? <span className="font-medium"> · {Math.floor(item.audioSeconds / 60)}:{String(Math.round(item.audioSeconds % 60)).padStart(2, "0")}</span> : null}
            </button>
          )}
          <button type="button" onClick={requestHuman} className="flex h-10 items-center gap-1.5 text-[15px] font-semibold text-primary">
            <Icon name="support_agent" size={20} /> {t("human")}
          </button>
        </div>
      )}
    </div>
  );
}

export const TRUST_ICON = { verified: "verified", engine: "calculate", checked: "task_alt" } as const;

/** How the reply was checked: a quiet trust signal next to the agent label. */
function VerificationBadge({ item }: { item: Assistant }) {
  const t = useT();
  const v = item.verification;
  if (!v || v.level === "blocked") return null;
  const label = v.level === "verified" ? (v.sources === 1 ? t("verifiedOne") : t("verified", { n: v.sources }))
    : v.level === "engine" ? t("engine") : t("checked");
  const level = v.level;
  // Tapping the label explains it. The hit area is 44 px tall although the label stays small.
  return (
    <button type="button" aria-label={`${label}. ${t("trustWhat")}`}
      onClick={() => openSheet("trust", { trustLevel: level })}
      className="relative inline-flex h-6 items-center gap-1 text-xs font-semibold text-success before:absolute before:-inset-x-2 before:-inset-y-2.5 before:content-['']">
      <Icon name={TRUST_ICON[level]} size={15} /> {label}
      <Icon name="info" size={14} className="text-ink-3" />
    </button>
  );
}

function Feedback({ item }: { item: Assistant }) {
  const t = useT();
  if (item.fallback) return null;
  return (
    <span className="flex items-center gap-1">
      {(["up", "down"] as const).map((r) => (
        <button key={r} type="button" aria-label={t(r === "up" ? "helpful" : "notHelpful")} aria-pressed={item.feedback === r}
          onClick={() => void rateReply(item.id, item.traceId, r)}
          className={cn("flex size-10 items-center justify-center rounded-full transition-colors",
            item.feedback === r ? "bg-primary-soft text-primary" : "text-ink-3 hover:bg-surface-2")}>
          <Icon name={r === "up" ? "thumb_up" : "thumb_down"} size={19} fill={item.feedback === r} />
        </button>
      ))}
    </span>
  );
}

/** Follow-up questions from the server, under the latest reply. Tapping one asks it (answered aloud). */
export function Suggestions({ items }: { items: string[] }) {
  const t = useT();
  const ready = useSession((s) => canTalk(s) && s.turn === "idle");
  if (!items.length || !ready) return null;
  return (
    <div className="flex flex-col gap-2.5">
      <span className="text-sm font-semibold text-ink-3">{t("askNext")}</span>
      <div className="flex flex-wrap gap-2">
        {items.map((s, i) => (
          <motion.button key={s} type="button" dir="auto" onClick={() => sendSuggestion(s)}
            initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 + i * 0.06, duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
            className="card rounded-full px-4 py-2.5 text-left text-[15px] font-medium leading-5 text-primary transition-[background-color,transform] duration-150 hover:bg-primary-soft active:scale-[0.98]">
            {s}
          </motion.button>
        ))}
      </div>
    </div>
  );
}

/** A message from the person handling the conversation. */
export function AgentMessage({ name, text }: { name: string; text: string }) {
  const t = useT();
  return (
    <div className="max-w-[92%] rounded-[20px] rounded-tl-md bg-info-soft px-4 pb-3.5 pt-3">
      <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-info">
        <Icon name="support_agent" size={16} /> {name || t("fromTeam")}
      </span>
      <p dir="auto" className="mt-1.5 text-[17px] leading-[25px]">{text}</p>
    </div>
  );
}

/** The safe reply when the checks blocked an answer. A feature, not an error. */
function FallbackBubble({ children }: { children: ReactNode }) {
  const t = useT();
  const handoff = useSession(withPerson);
  return (
    <div className="card flex flex-col gap-3.5 rounded-tl-md p-4">
      <div className="flex gap-3">
        <span className="flex size-10 flex-none items-center justify-center rounded-xl bg-primary-soft text-primary">
          <Icon name="find_in_page" />
        </span>
        <p dir="auto" className="text-[17px] leading-[25px]">{children}</p>
      </div>
      {!handoff && (
        <>
          <Button onClick={requestHuman} className="w-full"><Icon name="support_agent" size={20} /> {t("connectPerson")}</Button>
          <p className="text-center text-sm text-ink-3">{t("orAskAnother")}</p>
        </>
      )}
    </div>
  );
}

export function SystemNote({ icon, text, tone, vars }: {
  icon: string; text: StringKey; tone?: "success" | "muted"; vars?: Record<string, string | number>;
}) {
  const t = useT();
  return (
    <div className="flex items-center gap-3 py-1 text-sm text-ink-2" role="status">
      <span className="h-px flex-1 bg-line" />
      <span className="flex items-center gap-1.5 text-center">
        <Icon name={icon} size={17} className={tone === "success" ? "text-success" : "text-ink-3"} />
        {t(text, vars)}
      </span>
      <span className="h-px flex-1 bg-line" />
    </div>
  );
}

export function ResetNote() {
  const t = useT();
  return (
    <div className="card flex flex-col items-center gap-1 px-4 py-3.5 text-center">
      <span className="flex items-center gap-2 text-[15px] font-semibold">
        <Icon name="restart_alt" size={20} className="text-primary" /> {t("resetTitle")}
      </span>
      <span className="text-sm leading-5 text-ink-2">{t("resetBody")}</span>
    </div>
  );
}

/** While the person is recording. */
export function ListeningBubble() {
  const t = useT();
  return (
    <div className="ml-auto flex h-[52px] items-center gap-3 rounded-[22px] rounded-br-md bg-primary-soft px-5 text-[17px] font-medium text-primary">
      <VoiceBars mode="listening" height={20} /> {t("listening")}
    </div>
  );
}

const STEP_ORDER = ["transcribing", "thinking", "searching", "comparing", "calculating", "checking"] as const;

/** While Sahaj works on the reply: the steps the server reported, the current one spinning. */
export function ThinkingBubble() {
  const t = useT();
  const history = useSession((s) => s.statusHistory);
  const sending = useSession((s) => s.turn === "sending");
  const steps = history.filter((s) => (STEP_ORDER as readonly string[]).includes(s));
  return (
    <div className="card flex w-fit min-w-[240px] max-w-[80%] flex-col gap-2.5 rounded-tl-md px-4 py-3.5" aria-live="polite">
      <VoiceBars mode="thinking" height={20} />
      {sending && <span className="text-[15px] text-ink-2">{t("sending")}</span>}
      {steps.length > 0 && (
        <ol className="relative flex flex-col gap-2 before:absolute before:bottom-2 before:left-[8.5px] before:top-2 before:w-px before:bg-line">
          {steps.map((step, i) => {
            const current = i === steps.length - 1;
            return (
              <motion.li key={step} initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
                className={cn("relative flex items-center gap-2.5 text-[15px]", current ? "font-semibold text-ink" : "text-ink-2")}>
                <span className="flex size-[18px] flex-none items-center justify-center rounded-full bg-surface">
                  {current
                    ? <Icon name="progress_activity" size={18} className="animate-spin text-primary" />
                    : <Icon name="check_circle" size={18} fill className="text-success" />}
                </span>
                {t(`step_${step}` as StringKey)}
              </motion.li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

/** Opens the citations sheet for a message, highlighting one source. */
export function openCitation(itemId: string, citationId: string) {
  openSheet("citations", { citation: { itemId, citationId } });
}
