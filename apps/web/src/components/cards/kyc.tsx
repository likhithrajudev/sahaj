import { motion, useReducedMotion } from "motion/react";
import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { useT, type StringKey } from "@/lib/i18n";
import { cancelHandoff } from "@/lib/session";
import { cn } from "@/lib/utils";
import type { HandoffState } from "@/store/session";
import { useUi } from "@/store/ui";

const CALL_MINUTES = 30;

/** Re-renders every `ms` so "in 12 min" stays true while the card is open. */
function useNow(ms = 30_000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

function relative(when: Date, now: number): [StringKey, Record<string, number>?] {
  const minutes = Math.round((when.getTime() - now) / 60_000);
  if (minutes < -CALL_MINUTES) return ["kycPast"];
  if (minutes <= 5) return ["kycNow"];
  if (minutes < 60) return ["kycInMinutes", { n: minutes }];
  const days = Math.round((startOfDay(when) - startOfDay(new Date(now))) / 86_400_000);
  if (days === 0) return ["kycInHours", { n: Math.round(minutes / 60) }];
  if (days === 1) return ["kycTomorrow"];
  return ["kycInDays", { n: days }];
}

const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

/** A calendar file for the appointment, with a reminder 15 minutes before. */
function downloadIcs(when: Date, url: string | null, reference: string, title: string) {
  const stamp = (d: Date) => d.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
  const esc = (s: string) => s.replace(/[\\,;]/g, (c) => `\\${c}`).replace(/\n/g, "\\n");
  const description = esc(`Reference ${reference}${url ? `\nJoin: ${url}` : ""}`);
  const ics = [
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Sahaj//Video KYC//EN", "BEGIN:VEVENT",
    `UID:${reference}@sahaj`, `DTSTAMP:${stamp(new Date())}`, `DTSTART:${stamp(when)}`,
    `DTEND:${stamp(new Date(when.getTime() + CALL_MINUTES * 60_000))}`, `SUMMARY:${esc(title)}`, `DESCRIPTION:${description}`,
    ...(url ? [`URL:${url}`] : []),
    "BEGIN:VALARM", "TRIGGER:-PT15M", "ACTION:DISPLAY", `DESCRIPTION:${esc(title)}`, "END:VALARM",
    "END:VEVENT", "END:VCALENDAR",
  ].join("\r\n");
  const href = URL.createObjectURL(new Blob([ics], { type: "text/calendar" }));
  const a = Object.assign(document.createElement("a"), { href, download: "video-kyc.ics" });
  a.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

const READY: [string, StringKey][] = [
  ["badge", "kycReadyPan"], ["id_card", "kycReadyId"], ["light_mode", "kycReadyPlace"], ["wifi", "kycReadyNet"],
];

/** The video KYC request in the conversation: where it is, the booked slot, and the way into the call. */
export function KycCard({ handoff }: { handoff: HandoffState }) {
  const t = useT();
  const lang = useUi((s) => s.lang);
  const now = useNow();
  const locale = lang === "hi" ? "hi-IN" : "en-IN";
  const when = handoff.case?.scheduled_for ? new Date(handoff.case.scheduled_for) : null;
  const url = handoff.case?.meeting_url ?? null;
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(handoff.reference);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch { /* clipboard blocked: the number is selectable */ }
  };
  const [rel, vars] = when ? relative(when, now) : ["kycBooking" as StringKey];
  const soon = !!when && rel === "kycNow";

  return (
    <section className="card flex flex-col gap-5 p-5" aria-label={t("kycTitle")}>
      <div className="flex items-center gap-3.5">
        <span className="flex size-14 flex-none items-center justify-center rounded-2xl text-white shadow-talk" style={{ background: "var(--hero)" }}>
          <Icon name="videocam" size={30} />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h3 className="text-[24px] font-semibold leading-[30px] tracking-[-0.015em]">{t("kycTitle")}</h3>
          <span className={cn("flex w-fit items-center gap-2 rounded-full px-2.5 py-1 text-[13px] font-semibold",
            when ? "bg-success-soft text-success" : "bg-warn-soft text-warm-ink")} role="status">
            <span className="relative flex size-2">
              {!when && <span className="ping-soft absolute inset-0 rounded-full bg-current" />}
              <span className="relative size-2 rounded-full bg-current" />
            </span>
            {t(when ? "kycBooked" : "kycBooking")}
          </span>
        </div>
      </div>

      <ol className="flex flex-col">
        <Step state="done" title={t("kycRequested")}>
          <span className="flex items-center gap-2">
            {t("kycReference")} <b className="select-all font-mono font-medium tracking-wide text-ink">{handoff.reference}</b>
            <button type="button" onClick={copy} aria-label={t("copy")}
              className="flex size-8 items-center justify-center rounded-full text-primary transition-colors hover:bg-primary-soft">
              <Icon name={copied ? "check" : "content_copy"} size={16} />
            </button>
          </span>
        </Step>
        <Step state={when ? "done" : "current"} title={t(when ? "kycBooked" : "kycBooking")}>
          {when
            ? when.toLocaleString(locale, { weekday: "long", day: "numeric", month: "long", hour: "numeric", minute: "2-digit" })
            : handoff.agentName ? t("kycBookingAgent", { name: handoff.agentName }) : t("kycBookingWaiting")}
        </Step>
        <Step state={when ? "current" : "next"} title={t("kycCall")} last>
          {t("kycStep3Body")}
        </Step>
      </ol>

      {when && (
        <Appointment when={when} locale={locale} soon={soon} label={t(rel, vars)}>
          {url ? (
            <>
              <a href={url} target="_blank" rel="noopener noreferrer"
                className={cn("flex h-[52px] items-center justify-center gap-2 rounded-full bg-primary px-6 text-[17px] font-semibold text-on-primary shadow-talk transition-transform hover:bg-primary-strong active:scale-[0.98]",
                  soon && "ring-4 ring-primary/25")}>
                <Icon name="videocam" size={22} /> {t("kycJoin")}
              </a>
              <p className="text-center text-[13px] leading-[18px] text-ink-2">{t("kycJoinEarly")}</p>
            </>
          ) : (
            <p className="flex gap-2 rounded-xl bg-info-soft px-3 py-2.5 text-sm leading-5 text-ink">
              <Icon name="info" size={18} className="flex-none text-info" /> {t("kycLinkSoon")}
            </p>
          )}
          <Button variant="neutral" size="md" onClick={() => downloadIcs(when, url, handoff.reference, t("kycEventTitle"))}>
            <Icon name="calendar_add_on" size={20} /> {t("kycAddCalendar")}
          </Button>
        </Appointment>
      )}

      <div>
        <h4 className="mb-2.5 text-[15px] font-semibold text-ink-2">{t("kycReady")}</h4>
        <ul className="grid grid-cols-2 gap-2">
          {READY.map(([icon, key]) => (
            <li key={key} className="flex items-center gap-2.5 rounded-xl bg-surface-muted px-3 py-2.5 text-sm leading-[18px]">
              <Icon name={icon} size={20} className="flex-none text-primary" /> {t(key)}
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-col gap-2 text-sm leading-5 text-ink-3">
        <p className="flex gap-2"><Icon name="shield_person" size={18} className="flex-none" /> {t("kycWho")}</p>
        <p className="flex gap-2"><Icon name="support_agent" size={18} className="flex-none" /> {t("kycMeanwhile")}</p>
      </div>
      <Button variant="neutral" size="md" onClick={cancelHandoff}>{t("kycCancel")}</Button>
    </section>
  );
}

function Appointment({ when, locale, soon, label, children }: { when: Date; locale: string; soon: boolean; label: string; children: ReactNode }) {
  const reduce = useReducedMotion();
  return (
    <motion.div initial={reduce ? false : { opacity: 0, y: 8, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
      className="flex flex-col gap-3 rounded-[22px] bg-surface-muted p-4">
      <div className="flex items-center gap-4">
        <div className="flex w-[64px] flex-none flex-col overflow-hidden rounded-2xl bg-surface text-center shadow-card">
          <span className="bg-primary py-1 text-[12px] font-semibold uppercase tracking-wider text-on-primary">
            {when.toLocaleDateString(locale, { month: "short" })}
          </span>
          <span className="py-1.5 text-[28px] font-bold leading-8 tabular-nums">{when.getDate()}</span>
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="text-[15px] font-medium text-ink-2">{when.toLocaleDateString(locale, { weekday: "long" })}</span>
          <span className="text-[26px] font-semibold leading-8 tabular-nums tracking-[-0.015em]">
            {when.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" })}
          </span>
        </div>
        <span className={cn("flex-none rounded-full px-2.5 py-1 text-[13px] font-semibold",
          soon ? "bg-primary text-on-primary" : "bg-surface text-primary shadow-card")}>{label}</span>
      </div>
      {children}
    </motion.div>
  );
}

function Step({ state, title, last, children }: { state: "done" | "current" | "next"; title: string; last?: boolean; children: ReactNode }) {
  return (
    <li className="flex gap-3.5">
      <div className="flex flex-col items-center">
        <span className={cn("relative flex size-7 flex-none items-center justify-center rounded-full",
          state === "done" && "bg-success text-white",
          state === "current" && "bg-primary-soft text-primary ring-2 ring-primary",
          state === "next" && "border-2 border-line-2 text-ink-3")}>
          {state === "done" ? <Icon name="check" size={16} /> : <span className={cn("size-2 rounded-full bg-current", state === "current" && "ping-soft")} />}
        </span>
        {!last && <span className={cn("my-1 w-0.5 flex-1 rounded-full", state === "done" ? "bg-success" : "bg-line")} />}
      </div>
      <div className={cn("flex min-w-0 flex-1 flex-col gap-0.5", !last && "pb-4")}>
        <span className={cn("text-[17px] font-semibold leading-7", state === "next" && "text-ink-3")}>{title}</span>
        <span className="text-[15px] leading-[21px] text-ink-2">{children}</span>
      </div>
    </li>
  );
}
