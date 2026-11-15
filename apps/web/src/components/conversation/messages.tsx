import type { AgentName } from "@sahaj/contracts";
import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { useT, type StringKey } from "@/lib/i18n";
import { replay, requestHuman } from "@/lib/session";
import { cn } from "@/lib/utils";
import { useSession, type TimelineItem } from "@/store/session";
import { useUi } from "@/store/ui";

/** Cards and messages rise 12 px and fade in, 280 ms (Motion foundations). */
export function Rise({ children, className }: { children: ReactNode; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div className={className}
      initial={reduce ? { opacity: 0 } : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1] }}>
      {children}
    </motion.div>
  );
}

export function UserBubble({ text, children }: { text?: string; children?: ReactNode }) {
  return (
    <div dir="auto" className="ml-auto max-w-[85%] rounded-[20px] rounded-br-md bg-bubble px-4 py-3 text-[17px] leading-[25px] text-on-bubble">
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
    <div className="max-w-[92%] rounded-[20px] border border-line bg-surface px-4 pb-3.5 pt-3.5">
      <AgentBadge agent={item.agent} question={item.replyKind === "ask" && item.agent !== "advice"} />
      <p dir="auto" className="mt-2 text-[17px] leading-[25px]">{children}</p>
      {item.textOnly && (
        <p className="mt-2 flex items-center gap-1.5 text-[13px] font-semibold text-info">
          <Icon name="subtitles" size={17} /> {t("textOnlyNoAudio")}
        </p>
      )}
      {isLatest && (item.audioUrl || item.replyKind !== "ask") && (
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          {item.audioUrl && !speakingThis && (
            <button type="button" onClick={() => replay(item.audioUrl!)} disabled={turn !== "idle"}
              className="flex h-10 items-center gap-1.5 rounded-xl bg-primary-soft px-3.5 text-[15px] font-semibold text-primary disabled:opacity-50">
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

/** The safe reply when the checks blocked an answer. A feature, not an error. */
function FallbackBubble({ children }: { children: ReactNode }) {
  const t = useT();
  const handoff = useSession((s) => !!s.handoff);
  return (
    <div className="flex flex-col gap-3 rounded-[20px] border border-line bg-surface p-4">
      <div className="flex gap-3">
        <span className="flex size-10 flex-none items-center justify-center rounded-xl bg-surface-2 text-primary">
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

export function SystemNote({ icon, text, tone }: { icon: string; text: StringKey; tone?: "success" | "muted" }) {
  const t = useT();
  return (
    <div className="flex items-center gap-3 py-1 text-sm text-ink-2" role="status">
      <span className="h-px flex-1 bg-line" />
      <span className="flex items-center gap-1.5 text-center">
        <Icon name={icon} size={17} className={tone === "success" ? "text-success" : "text-ink-3"} />
        {t(text)}
      </span>
      <span className="h-px flex-1 bg-line" />
    </div>
  );
}

export function ResetNote() {
  const t = useT();
  return (
    <div className="flex flex-col items-center gap-1 rounded-[20px] border border-line bg-surface px-4 py-3.5 text-center">
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
    <div className="ml-auto flex h-[52px] items-center gap-2.5 rounded-[20px] border-[1.5px] border-dashed border-primary px-5 text-[17px] text-ink-2">
      <Icon name="graphic_eq" size={22} className="text-primary" /> {t("listening")}
    </div>
  );
}

const STEP_ORDER = ["understanding", "searching", "comparing", "calculating", "thinking", "checking"] as const;

/** While Sahaj works on the reply: the steps the server reported, the current one spinning. */
export function ThinkingBubble() {
  const t = useT();
  const history = useSession((s) => s.statusHistory);
  const sending = useSession((s) => s.turn === "sending");
  const steps = history.filter((s) => STEP_ORDER.includes(s));
  return (
    <div className="flex w-fit min-w-[220px] max-w-[80%] flex-col gap-2 rounded-[20px] border border-line bg-surface px-4 py-3.5" aria-live="polite">
      <div className="flex gap-1.5" aria-hidden>
        {[0, 1, 2].map((i) => <span key={i} className="dot-breathe size-2 rounded-full bg-primary" />)}
      </div>
      {sending && <span className="text-[15px] text-ink-2">{t("sending")}</span>}
      {steps.map((step, i) => {
        const current = i === steps.length - 1;
        return (
          <span key={step} className={cn("flex items-center gap-2 text-[15px]", current ? "font-semibold text-ink" : "text-ink-2")}>
            {current
              ? <Icon name="progress_activity" size={18} className="animate-spin text-primary" />
              : <Icon name="check" size={18} className="text-success" />}
            {t(`step_${step}` as StringKey)}
          </span>
        );
      })}
    </div>
  );
}

/** Opens the citations sheet for a message, highlighting one source. */
export function openCitation(itemId: string, citationId: string) {
  useUi.setState({ sheet: "citations", citation: { itemId, citationId } });
}
