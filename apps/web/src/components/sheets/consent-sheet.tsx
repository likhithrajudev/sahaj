import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Sheet } from "@/components/ui/sheet";
import { useT } from "@/lib/i18n";
import { answerConsent } from "@/lib/session";
import { useSession } from "@/store/session";

/** The conversation consent: shown verbatim, equal-weight choices, no way to dismiss without answering. */
export function ConsentSheet() {
  const t = useT();
  const prompt = useSession((s) => s.consentPrompt);
  return (
    <Sheet open={!!prompt} dismissible={false} label={t("consentTitle")}>
      <div className="flex items-center gap-3.5">
        <span className="flex size-12 items-center justify-center rounded-2xl text-white shadow-talk" style={{ background: "var(--hero)" }}>
          <Icon name="shield_person" />
        </span>
        <h2 className="text-[24px] font-semibold tracking-[-0.015em]">{t("consentTitle")}</h2>
      </div>
      <p className="mt-5 whitespace-pre-line text-[17px] leading-[26px]">{prompt?.text}</p>
      <p className="mt-4 flex items-center gap-1.5 text-[13px] text-ink-3">
        <Icon name="description" size={16} /> {t("consentNotice")} {prompt?.version} · {t("purposeConversation")}
      </p>
      <div className="mt-6 grid grid-cols-2 gap-3 pb-2">
        <Button variant="outline" onClick={() => answerConsent(false)}>{t("notNow")}</Button>
        <Button onClick={() => answerConsent(true)}>{t("agree")}</Button>
      </div>
    </Sheet>
  );
}
