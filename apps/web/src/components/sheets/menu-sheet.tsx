import type { ConsentPurpose } from "@sahaj/contracts";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useRef, useState, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Sheet } from "@/components/ui/sheet";
import { useT, type StringKey } from "@/lib/i18n";
import { signOut, useAuth } from "@/lib/auth";
import { withdrawConsent } from "@/lib/session";
import { cn } from "@/lib/utils";
import { pwa } from "@/pwa";
import { kycCase, useSession, type ConsentInfo } from "@/store/session";
import { closeAllSheets, closeSheet, openSheet, useUi, type Theme } from "@/store/ui";

/** Languages as the backend supports them (services/tts.py). */
const LANGUAGES: { mode: StringKey; tone: "success" | "warm" | "info"; names: string }[] = [
  { mode: "fullVoice", tone: "success", names: "English, Hindi, Hinglish, Bengali, Tamil, Telugu, Kannada, Marathi, Gujarati, Punjabi, Malayalam, Odia" },
  { mode: "approxVoice", tone: "warm", names: "Nepali, Maithili, Dogri, Konkani, Sanskrit, Bodo, Assamese" },
  { mode: "textOnlyMode", tone: "info", names: "Urdu, Kashmiri, Sindhi, Santali, Manipuri" },
];

export function MenuSheet() {
  const t = useT();
  const consent = useSession((s) => s.consent);
  const sessionId = useSession((s) => s.sessionId);
  const kyc = useSession(kycCase);
  const lang = useUi((s) => s.lang);
  const theme = useUi((s) => s.theme);
  const [copied, setCopied] = useState(false);

  return (
    <Sheet name="menu" onClose={closeSheet} label={t("menu")}>
      <div className="flex flex-col gap-5 pb-4">
        <Account />
        <Section title={t("menuPrivacy")}>
          <div className="overflow-hidden rounded-2xl bg-surface-muted">
            <ConsentRow purpose="conversation" label={t("conversation")} info={consent.conversation} />
            <div className="mx-4 h-px bg-line" />
            <ConsentRow purpose="needs_analysis" label={t("personalDetails")} info={consent.needs_analysis} />
            <div className="mx-4 h-px bg-line" />
            <ConsentRow purpose="video_kyc" label={t("kycTitle")} info={consent.video_kyc} />
          </div>
        </Section>

        <Section title={t("interfaceLanguage")}>
          <Segmented value={lang} onChange={(v) => useUi.setState({ lang: v })}
            options={[["en", "English"], ["hi", "हिन्दी"]]} />
        </Section>

        <Section title={t("appearance")}>
          <Segmented<Theme> value={theme} onChange={(v) => useUi.setState({ theme: v })}
            options={[["system", t("themeSystem")], ["light", t("themeLight")], ["dark", t("themeDark")]]} />
        </Section>

        <Section title={t("menuLanguages")}>
          <div className="flex flex-col gap-2.5">
            {LANGUAGES.map((l) => (
              <div key={l.mode} className="flex flex-col items-start gap-1.5">
                <Badge tone={l.tone}>{t(l.mode)}</Badge>
                <p className="text-[15px] leading-[21px] text-ink-2">{l.names}</p>
              </div>
            ))}
          </div>
        </Section>

        <nav className="flex flex-col border-t border-line">
          <Row icon="videocam" onClick={() => openSheet("kyc")}>
            <span className="flex items-center gap-2">{t("kycMenu")}{kyc && <Badge tone={kyc.case?.scheduled_for ? "success" : "warm"}>{t(kyc.case?.scheduled_for ? "kycBooked" : "kycBooking")}</Badge>}</span>
          </Row>
          <Row icon="description" onClick={() => openSheet("documents")}>Policy documents</Row>
          <Row icon="task_alt" onClick={() => openSheet("claim")}>Prepare a claim</Row>
          <Row icon="calculate" onClick={() => openSheet("loan")}>Prepare a loan application</Row>
          {!pwa.isStandalone() && <Row icon="install_mobile" onClick={() => openSheet("install")}>{t("menuInstall")}</Row>}
          <Row icon="info" onClick={() => openSheet("about")}>{t("menuAbout")}</Row>
        </nav>

        {sessionId && (
          <button type="button" onClick={async () => {
            try { await navigator.clipboard.writeText(sessionId); setCopied(true); setTimeout(() => setCopied(false), 1600); } catch { /* selectable */ }
          }} className="flex items-center justify-between rounded-xl bg-surface-muted px-3.5 py-3 text-sm text-ink-2">
            <span>{t("sessionRef")} <b className="select-all font-mono font-medium text-ink">{sessionId}</b></span>
            <Icon name={copied ? "check" : "content_copy"} size={20} className="text-primary" />
          </button>
        )}
      </div>
    </Sheet>
  );
}

function Account() {
  const t = useT();
  const user = useAuth((s) => s.user);
  if (!user) return null;
  return (
    <Section title={t("account")}>
      <div className="flex items-center gap-3 rounded-2xl bg-surface-muted px-4 py-3">
        {user.picture
          ? <img src={user.picture} alt="" className="size-10 rounded-full" referrerPolicy="no-referrer" />
          : <span className="flex size-10 items-center justify-center rounded-full bg-primary-soft text-primary"><Icon name="account_circle" /></span>}
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-[17px] font-semibold">{user.name || user.email}</span>
          <span className="truncate text-[13px] text-ink-2">{user.email}</span>
        </div>
        <Button variant="neutral" size="sm" className="h-11 rounded-xl px-3.5" onClick={() => { closeAllSheets(); setTimeout(() => void signOut(), 280); }}>
          <Icon name="logout" size={18} /> {t("signOut")}
        </Button>
      </div>
    </Section>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="mb-2.5 text-[15px] font-semibold text-ink-2">{title}</h3>
      {children}
    </section>
  );
}

function ConsentRow({ purpose, label, info }: { purpose: ConsentPurpose; label: string; info: ConsentInfo }) {
  const t = useT();
  const granted = info.state === "granted";
  const time = info.at ? new Date(info.at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false }) : null;
  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <Icon name={granted ? "verified_user" : "remove_moderator"} className={granted ? "text-success" : "text-ink-3"} />
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="text-[17px] font-semibold">{label}</span>
        <span className="text-[13px] text-ink-2">
          {t(granted ? "granted" : info.state === "revoked" ? "withdrawn" : "notGranted")}
          {info.version && <> · {info.version}</>}{time && <> · {time}</>}
        </span>
      </div>
      {granted && (
        <Button variant="neutral" size="sm" className="h-11 rounded-xl px-3.5 text-error"
          onClick={() => useUi.setState({ confirmWithdraw: purpose })}>
          {t("withdraw")}
        </Button>
      )}
    </div>
  );
}

function Segmented<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: [T, string][] }) {
  return (
    <div className="grid rounded-full bg-surface-2 p-1" style={{ gridTemplateColumns: `repeat(${options.length}, 1fr)` }} role="radiogroup">
      {options.map(([v, label]) => (
        <button key={v} type="button" role="radio" aria-checked={value === v} onClick={() => onChange(v)}
          className={cn("h-10 rounded-full text-[15px] font-semibold transition-[background-color,color,box-shadow] duration-200",
            value === v ? "bg-surface text-primary shadow-card" : "text-ink-2 hover:text-ink")}>
          {label}
        </button>
      ))}
    </div>
  );
}

function Row({ icon, iconClass, onClick, children }: { icon: string; iconClass?: string; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} className="flex min-h-14 items-center gap-3 border-b border-line text-left text-[17px]">
      <Icon name={icon} className={iconClass ?? "text-primary"} />
      <span className="flex-1">{children}</span>
      <Icon name="chevron_right" className="text-ink-3" />
    </button>
  );
}

/** Centred confirmation before withdrawing a consent. */
export function WithdrawDialog() {
  const t = useT();
  const asked = useUi((s) => s.confirmWithdraw);
  const reduce = useReducedMotion();
  // the question stays as it was while the dialog fades away
  const last = useRef(asked);
  if (asked) last.current = asked;
  const purpose = last.current;
  const close = () => useUi.setState({ confirmWithdraw: null });
  const [title, body]: [StringKey, StringKey] = purpose === "conversation" ? ["withdrawTitle", "withdrawBody"]
    : purpose === "video_kyc" ? ["withdrawKycTitle", "withdrawKycBody"] : ["withdrawDetailsTitle", "withdrawDetailsBody"];
  return (
    <AnimatePresence>
      {asked && purpose && (
        // Over the menu sheet: its taps and keys stay here, so the menu underneath doesn't take them as "close".
        <motion.div key="withdraw" className="pointer-events-auto fixed inset-0 z-[70] flex items-center justify-center px-5"
          style={{ background: "var(--scrim-stacked)" }} role="alertdialog" aria-modal="true" aria-labelledby="withdraw-title"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: { duration: 0.16, ease: [0.4, 0, 1, 1] } }}
          transition={{ duration: 0.2 }}
          onPointerDown={(e) => e.stopPropagation()} onClick={close}
          onKeyDown={(e) => { e.stopPropagation(); if (e.key === "Escape") close(); }}>
          <motion.div className="w-full max-w-[400px] rounded-[28px] bg-surface p-6 shadow-raised" onClick={(e) => e.stopPropagation()}
            initial={reduce ? false : { opacity: 0, scale: 0.94, y: 8 }} animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.97, transition: { duration: 0.16, ease: [0.4, 0, 1, 1] } }}
            transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}>
            <h2 id="withdraw-title" className="text-[22px] font-semibold leading-7">{t(title)}</h2>
            <p className="mt-3 text-[17px] leading-[25px] text-ink-2">{t(body)}</p>
            <div className="mt-5 grid grid-cols-2 gap-3">
              <Button variant="neutral" onClick={close} autoFocus>{t("keep")}</Button>
              <Button variant="danger" onClick={() => { withdrawConsent(purpose); close(); }}>{t("withdraw")}</Button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
