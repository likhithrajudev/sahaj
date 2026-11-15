import { Icon } from "@/components/ui/icon";
import { useT } from "@/lib/i18n";
import { reconnectNow } from "@/lib/session";
import { useSession } from "@/store/session";

/** Reconnecting / offline banner under the header. */
export function ConnectionBanner() {
  const t = useT();
  const connection = useSession((s) => s.connection);
  const hasSession = useSession((s) => s.sessionId !== null || s.timeline.length > 0);
  if (connection === "reconnecting" || (connection === "connecting" && hasSession)) {
    return (
      <div role="status" className="mx-4 mt-1 flex items-start gap-3 rounded-[14px] bg-warn-soft px-4 py-3 text-[15px] leading-[21px] text-warm-ink lg:mx-auto lg:w-full lg:max-w-[720px]">
        <Icon name="sync" size={20} className="mt-px animate-spin [animation-duration:2.4s]" />
        {t("reconnectingBanner")}
      </div>
    );
  }
  if (connection === "offline") {
    return (
      <div role="status" className="mx-4 mt-1 flex items-center gap-3 rounded-[14px] bg-surface-2 px-4 py-3 text-[15px] text-ink lg:mx-auto lg:w-full lg:max-w-[720px]">
        <Icon name="wifi_off" size={20} />
        <span className="flex-1">{t("offlineTitle")}</span>
        <button type="button" className="font-semibold text-primary" onClick={reconnectNow}>{t("retry")}</button>
      </div>
    );
  }
  return null;
}
