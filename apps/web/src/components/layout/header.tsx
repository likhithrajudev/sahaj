import { LogoMark } from "@/components/brand/logo";
import { Icon } from "@/components/ui/icon";
import { useT, type StringKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { pwa } from "@/pwa";
import { kycCase, useSession, withPerson } from "@/store/session";
import { openSheet } from "@/store/ui";

const STATUS: Record<string, [StringKey, string]> = {
  open: ["connected", "var(--success)"],
  connecting: ["connecting", "var(--ink-3)"],
  signed_out: ["connecting", "var(--ink-3)"],
  reconnecting: ["reconnectingShort", "var(--warn)"],
  offline: ["offline", "var(--error)"],
  handoff: ["withPerson", "var(--info)"],
  kyc: ["kycTitle", "var(--info)"],
};

export function Header() {
  const t = useT();
  const connection = useSession((s) => s.connection);
  const handoff = useSession(withPerson);
  const progress = useSession((s) => s.progress);
  const kyc = useSession((s) => !!kycCase(s));
  const [label, dot] = STATUS[kyc ? "kyc" : handoff ? "handoff" : connection];
  const live = connection === "connecting" || connection === "reconnecting";

  return (
    <header className="pt-safe z-20 flex-none">
      <div className="flex h-16 items-center gap-3 pl-[18px] pr-2 lg:px-7">
        <LogoMark size={36} />
        <div className="flex min-w-0 flex-col gap-0.5 lg:flex-row lg:items-center lg:gap-4">
          <span className="text-[20px] font-bold leading-5 tracking-[-0.025em] text-[var(--logo-word)]">Sahaj</span>
          <span className="flex w-fit items-center gap-1.5 text-xs font-medium leading-[14px] text-ink-2 lg:rounded-full lg:bg-surface lg:px-2.5 lg:py-1.5 lg:text-[13px] lg:shadow-card"
            aria-live="polite">
            <span className="relative flex size-[7px]">
              {live && <span className="ping-soft absolute inset-0 rounded-full" style={{ background: dot }} />}
              <span className="relative size-[7px] rounded-full" style={{ background: dot }} />
            </span>
            {t(label)}
          </span>
        </div>
        <div className="flex-1" />
        {!pwa.isStandalone() && (
          <button type="button" onClick={() => openSheet("install")}
            className="hidden h-11 items-center gap-1.5 rounded-full px-4 font-semibold text-primary transition-colors hover:bg-primary-soft lg:flex">
            <Icon name="install_desktop" size={22} /> {t("menuInstall")}
          </button>
        )}
        <button type="button" aria-label={t("menu")} onClick={() => openSheet("menu")}
          className="flex size-11 items-center justify-center rounded-full text-ink transition-colors hover:bg-surface-2">
          <Icon name="menu" />
        </button>
      </div>
      {progress && (
        <div className="flex flex-col gap-2 px-[18px] pb-3 lg:mx-auto lg:w-full lg:max-w-[720px]">
          <div className="flex justify-between text-[13px] font-medium text-ink-2">
            <span>{t("needsProgress")}</span>
            <span className="tabular-nums"><b className="font-semibold text-primary">{progress.step}</b> {t("of")} {progress.total}</span>
          </div>
          <div className="flex gap-1" role="progressbar" aria-label={t("needsProgress")} aria-valuemin={0}
            aria-valuemax={progress.total} aria-valuenow={progress.step}>
            {Array.from({ length: progress.total }, (_, i) => (
              <span key={i} className="h-1.5 flex-1 overflow-hidden rounded-full bg-line">
                <span className={cn("block h-full rounded-full bg-primary transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)]",
                  i < progress.step ? "translate-x-0" : "-translate-x-full")} />
              </span>
            ))}
          </div>
        </div>
      )}
    </header>
  );
}
