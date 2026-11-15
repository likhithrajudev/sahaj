import { motion, useReducedMotion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { useT } from "@/lib/i18n";
import { requestHuman, reviewConsent } from "@/lib/session";
import { cn } from "@/lib/utils";
import { openSheet } from "@/store/ui";

/** Spoken examples: hints for what to say, not buttons (the backend takes voice only). */
export const EXAMPLES: { icon: string; text: string; tone: "insurance" | "loan" | "language"; lang?: string }[] = [
  { icon: "health_and_safety", tone: "insurance", text: "What is the waiting period for pre-existing diseases?" },
  { icon: "compare_arrows", tone: "insurance", text: "Compare the Lotus and Neem health plans" },
  { icon: "family_restroom", tone: "insurance", text: "Which health insurance should I buy for my family?" },
  { icon: "calculate", tone: "loan", text: "What would the EMI be on 5 lakh at 11% for 3 years?" },
  { icon: "event_available", tone: "loan", text: "Can I repay my loan early without a penalty?" },
  { icon: "videocam", tone: "loan", text: "Book my video KYC" },
  { icon: "translate", tone: "language", text: "टर्म इंश्योरेंस और होल लाइफ में क्या फर्क है?", lang: "hi" },
];

const TONE = {
  insurance: "bg-primary-soft text-primary",
  loan: "bg-loan-soft text-loan",
  language: "bg-warm-soft text-warm-ink",
};

export function Welcome() {
  const t = useT();
  const reduce = useReducedMotion();
  // "Namaste." leads on its own line; the rest of the greeting follows (works for "।" too).
  const [hello, ...rest] = t("greeting").split(/(?<=[.।])\s+/);
  return (
    <div className="flex flex-col gap-7 pb-2 pt-3 lg:pt-10">
      <motion.div initial={reduce ? false : { opacity: 0, y: 8, filter: "blur(6px)" }}
        animate={{ opacity: 1, y: 0, filter: "blur(0px)" }} transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}>
        <h1 className="flex flex-col gap-1">
          <span className="text-[40px] font-bold leading-[44px] tracking-[-0.025em] text-primary-strong lg:text-[52px] lg:leading-[56px]">{hello}</span>
          {rest.length > 0 && (
            <span className="text-[26px] font-semibold leading-[32px] tracking-[-0.015em] lg:text-[30px] lg:leading-[38px]">{rest.join(" ")}</span>
          )}
        </h1>
        <p className="mt-3 max-w-[56ch] text-[17px] leading-[26px] text-ink-2">{t("greetingSub")}</p>
      </motion.div>
      <section>
        <h2 className="mb-3 flex items-center gap-2 text-[15px] font-semibold text-ink-2">
          <Icon name="record_voice_over" size={20} className="text-primary" /> {t("trySaying")}
        </h2>
        <ul className="card flex flex-col overflow-hidden">
          {EXAMPLES.map((e, i) => (
            <motion.li key={e.text} lang={e.lang}
              initial={reduce ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.12 + i * 0.05, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
              className="flex items-center gap-3.5 border-b border-line px-4 py-3 text-base leading-[22px] last:border-b-0">
              <span className={cn("flex size-9 flex-none items-center justify-center rounded-xl", TONE[e.tone])}>
                <Icon name={e.icon} size={20} />
              </span>
              <span>“{e.text}”</span>
            </motion.li>
          ))}
        </ul>
      </section>
      <motion.button type="button" onClick={() => openSheet("kyc")}
        initial={reduce ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        className="card flex items-center gap-3.5 px-4 py-3.5 text-left transition-transform active:scale-[0.99]">
        <span className="flex size-11 flex-none items-center justify-center rounded-2xl text-white" style={{ background: "var(--hero)" }}>
          <Icon name="videocam" size={24} />
        </span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="text-[17px] font-semibold leading-6">{t("kycWelcomeTitle")}</span>
          <span className="text-[15px] leading-[21px] text-ink-2">{t("kycWelcomeBody")}</span>
        </span>
        <Icon name="chevron_right" className="text-ink-3" />
      </motion.button>
    </div>
  );
}

export function ConsentDeclined() {
  const t = useT();
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 py-10 text-center">
      <span className="card flex size-[72px] items-center justify-center rounded-full text-ink-2"><Icon name="pause_circle" size={34} /></span>
      <h1 className="text-[22px] font-semibold">{t("declinedTitle")}</h1>
      <p className="max-w-[320px] text-[17px] leading-[25px] text-ink-2">{t("declinedBody")}</p>
      <Button onClick={reviewConsent}><Icon name="shield_person" size={20} /> {t("reviewConsent")}</Button>
      <Button variant="link" size="inline" onClick={requestHuman}><Icon name="support_agent" size={20} /> {t("human")}</Button>
    </div>
  );
}
