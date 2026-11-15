import type { ConsentPurpose } from "@sahaj/contracts";
import { useState, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Sheet } from "@/components/ui/sheet";
import { useT, type StringKey } from "@/lib/i18n";
import { signOut, useAuth } from "@/lib/auth";
import { withdrawConsent } from "@/lib/session";
import { cn } from "@/lib/utils";
import { pwa } from "@/pwa";
import { useSession, type ConsentInfo } from "@/store/session";
import { closeSheet, openSheet, useUi, type Theme } from "@/store/ui";

/** Languages as the backend supports them (services/tts.py). */
const LANGUAGES: { mode: StringKey; tone: "success" | "warm" | "info"; names: string }[] = [
  { mode: "fullVoice", tone: "success", names: "English, Hindi, Hinglish, Bengali, Tamil, Telugu, Kannada, Marathi, Gujarati, Punjabi, Malayalam, Odia" },
  { mode: "approxVoice", tone: "warm", names: "Nepali, Maithili, Dogri, Konkani, Sanskrit, Bodo, Assamese" },
  { mode: "textOnlyMode", tone: "info", names: "Urdu, Kashmiri, Sindhi, Santali, Manipuri" },
];

export function MenuSheet() {
  const t = useT();
  const open = useUi((s) => s.sheet === "menu");
  const consent = useSession((s) => s.consent);
  const sessionId = useSession((s) => s.sessionId);
  const lang = useUi((s) => s.lang);
  const theme = useUi((s) => s.theme);
  const [copied, setCopied] = useState(false);

  return (
    <Sheet open={open} onClose={closeSheet} label={t("menu")}>
      <div className="flex flex-col gap-5 pb-4">
        <Account />
        <Section title={t("menuPrivacy")}>
          <div className="overflow-hidden rounded-2xl bg-bg">
            <ConsentRow purpose="conversation" label={t("conversation")} info={consent.conversation} />
            <div className="mx-4 h-px bg-line" />
            <ConsentRow purpose="needs_analysis" label={t("personalDetails")} info={consent.needs_analysis} />
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
          {!pwa.isStandalone() && <Row icon="install_mobile" onClick={() => openSheet("install")}>{t("menuInstall")}</Row>}
          <Row icon="info" onClick={() => openSheet("about")}>{t("menuAbout")}</Row>
        </nav>

        {sessionId && (
          <button type="button" onClick={async () => {
            try { await navigator.clipboard.writeText(sessionId); setCopied(true); setTimeout(() => setCopied(false), 1600); } catch { /* selectable */ }
          }} className="flex items-center justify-between rounded-xl bg-bg px-3.5 py-3 text-sm text-ink-2">
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
      <div className="flex items-center gap-3 rounded-2xl bg-bg px-4 py-3">
        {user.picture
          ? <img src={user.picture} alt="" className="size-10 rounded-full" referrerPolicy="no-referrer" />
          : <span className="flex size-10 items-center justify-center rounded-full bg-primary-soft text-primary"><Icon name="account_circle" /></span>}
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-[17px] font-semibold">{user.name || user.email}</span>
          <span className="truncate text-[13px] text-ink-2">{user.email}</span>
        </div>
        <Button variant="neutral" size="sm" className="h-11 rounded-xl px-3.5" onClick={() => { closeSheet(); void signOut(); }}>
          <Icon name="logout" size={18} /> {t("signOut")}
        </Button>
      </div>
    </Section>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="mb-2.5 text-[13px] font-semibold uppercase tracking-[.1em] text-ink-2">{title}</h3>
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
    <div className="grid rounded-[14px] bg-bg p-1" style={{ gridTemplateColumns: `repeat(${options.length}, 1fr)` }} role="radiogroup">
      {options.map(([v, label]) => (
        <button key={v} type="button" role="radio" aria-checked={value === v} onClick={() => onChange(v)}
          className={cn("h-10 rounded-[10px] text-[15px] font-semibold", value === v ? "bg-surface text-primary shadow-sm" : "text-ink-2")}>
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
  const purpose = useUi((s) => s.confirmWithdraw);
  const conversation = purpose === "conversation"; // other purposes are managed elsewhere (memory, documents)
  const close = () => useUi.setState({ confirmWithdraw: null });
  if (!purpose) return null;
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center px-5" style={{ background: "var(--scrim)" }}
      role="alertdialog" aria-modal="true" aria-labelledby="withdraw-title" onClick={close}>
      <div className="w-full max-w-[400px] rounded-3xl bg-surface p-6" onClick={(e) => e.stopPropagation()}>
        <h2 id="withdraw-title" className="text-[22px] font-semibold leading-7">{t(conversation ? "withdrawTitle" : "withdrawDetailsTitle")}</h2>
        <p className="mt-3 text-[17px] leading-[25px] text-ink-2">{t(conversation ? "withdrawBody" : "withdrawDetailsBody")}</p>
        <div className="mt-5 grid grid-cols-2 gap-3">
          <Button variant="neutral" onClick={close} autoFocus>{t("keep")}</Button>
          <Button variant="danger" onClick={() => { withdrawConsent(purpose); close(); closeSheet(); }}>{t("withdraw")}</Button>
        </div>
      </div>
    </div>
  );
}
