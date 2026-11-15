import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { useT } from "@/lib/i18n";
import { requestHuman, reviewConsent } from "@/lib/session";

/** Spoken examples: hints for what to say, not buttons (the backend takes voice only). */
const EXAMPLES = [
  { icon: "health_and_safety", text: "What is the waiting period for pre-existing diseases?" },
  { icon: "compare_arrows", text: "Compare the Lotus and Neem health plans" },
  { icon: "family_restroom", text: "Which health insurance should I buy for my family?" },
  { icon: "calculate", text: "What would the EMI be on 5 lakh at 11% for 3 years?" },
  { icon: "event_available", text: "Can I repay my loan early without a penalty?" },
  { icon: "translate", text: "टर्म इंश्योरेंस और होल लाइफ में क्या फर्क है?", lang: "hi" },
];

export function Welcome() {
  const t = useT();
  return (
    <div className="flex flex-col gap-4 pb-2">
      <div>
        <h1 className="text-[26px] font-semibold leading-[34px]">{t("greeting")}</h1>
        <p className="mt-2 text-[17px] leading-[25px] text-ink-2">{t("greetingSub")}</p>
      </div>
      <div>
        <h2 className="mb-2.5 flex items-center gap-1.5 text-sm font-semibold uppercase tracking-[.08em] text-ink-2">
          <Icon name="record_voice_over" size={18} /> {t("trySaying")}
        </h2>
        <ul className="flex flex-col gap-2">
          {EXAMPLES.map((e) => (
            <li key={e.text} lang={e.lang} className="flex items-start gap-3 rounded-xl border border-dashed border-line-2 px-3.5 py-2 text-base leading-[22px]">
              <Icon name={e.icon} size={20} className="mt-0.5 text-primary" /> “{e.text}”
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function ConsentDeclined() {
  const t = useT();
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 py-10 text-center">
      <span className="flex size-[72px] items-center justify-center rounded-full bg-surface-2 text-ink-2"><Icon name="pause_circle" size={34} /></span>
      <h1 className="text-[22px] font-semibold">{t("declinedTitle")}</h1>
      <p className="max-w-[320px] text-[17px] leading-[25px] text-ink-2">{t("declinedBody")}</p>
      <Button onClick={reviewConsent}><Icon name="shield_person" size={20} /> {t("reviewConsent")}</Button>
      <Button variant="link" size="inline" onClick={requestHuman}><Icon name="support_agent" size={20} /> {t("human")}</Button>
    </div>
  );
}
