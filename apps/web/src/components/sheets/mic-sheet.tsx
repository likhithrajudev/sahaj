import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Sheet } from "@/components/ui/sheet";
import { useT } from "@/lib/i18n";
import { grantMicFromExplainer } from "@/lib/session";
import { pwa } from "@/pwa";
import { useSession } from "@/store/session";
import { closeSheet } from "@/store/ui";

/** Before the browser's permission prompt, explain why; if it was blocked, explain how to allow it. */
export function MicSheet() {
  const t = useT();
  const error = useSession((s) => s.micError);
  const explainer = !error;

  return (
    <Sheet name="mic" onClose={closeSheet} label={explainer ? t("micTitle") : t("blockedTitle")}>
      <div className="flex flex-col items-center gap-3 pb-2 text-center">
        <span className={`mt-2 flex size-[88px] items-center justify-center rounded-full ${explainer ? "bg-warm-soft" : "bg-error-soft"}`}>
          <span className={`flex size-16 items-center justify-center rounded-full ${explainer ? "bg-talk text-white" : "bg-error text-white"}`}>
            <Icon name={explainer ? "mic" : "mic_off"} size={30} fill />
          </span>
        </span>
        <h2 className="text-[22px] font-semibold">{explainer ? t("micTitle") : t("blockedTitle")}</h2>
        <p className="text-[17px] leading-[25px] text-ink-2">
          {explainer ? t("micBody")
            : error === "denied" ? (pwa.isIOS() ? t("blockedIOS") : t("blockedOther"))
            : error === "insecure" ? t("insecure")
            : error === "no-device" ? t("noMic")
            : error === "unsupported" ? t("unsupported")
            : t("serverError")}
        </p>
        {explainer && (
          <ul className="flex w-full flex-col gap-2.5 rounded-2xl bg-surface-muted px-4 py-3.5 text-left text-[15px]">
            <li className="flex items-center gap-3"><Icon name="touch_app" size={20} className="text-primary" />{t("micPoint1")}</li>
            <li className="flex items-center gap-3"><Icon name="timer" size={20} className="text-primary" />{t("micPoint2")}</li>
            <li className="flex items-center gap-3"><Icon name="delete_history" size={20} className="text-primary" />{t("micPoint3")}</li>
          </ul>
        )}
        <Button className="mt-2 w-full" onClick={explainer ? () => void grantMicFromExplainer() : () => {
          useSession.setState({ micError: null });
          closeSheet();
        }}>
          {explainer ? t("micContinue") : t("gotIt")}
        </Button>
      </div>
    </Sheet>
  );
}
