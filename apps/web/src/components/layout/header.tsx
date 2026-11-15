import { LogoMark } from "@/components/brand/logo";
import { Icon } from "@/components/ui/icon";
import { useT, type StringKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { pwa } from "@/pwa";
import { useSession, withPerson } from "@/store/session";
import { openSheet } from "@/store/ui";

const STATUS: Record<string, [StringKey, string]> = {
  open: ["connected", "var(--success)"],
  connecting: ["connecting", "var(--ink-3)"],
  signed_out: ["connecting", "var(--ink-3)"],
  reconnecting: ["reconnectingShort", "var(--warn)"],
  offline: ["offline", "var(--error)"],
  handoff: ["withPerson", "var(--info)"],
};

export function Header() {
  const t = useT();
  const connection = useSession((s) => s.connection);
  const handoff = useSession(withPerson);
  const progress = useSession((s) => s.progress);
  const [label, dot] = STATUS[handoff ? "handoff" : connection];

  return (
    <header className="pt-safe z-20 flex-none bg-bg lg:border-b lg:border-line">
      <div className="flex h-14 items-center gap-2.5 pl-[18px] pr-2 lg:h-16 lg:px-7">
        <LogoMark size={34} />
        <div className="flex min-w-0 flex-col gap-px lg:flex-row lg:items-center lg:gap-5">
          <span className="text-[19px] font-bold leading-5 tracking-[-0.025em] text-[var(--logo-word)]">Sahaj</span>
          <span className="flex items-center gap-[5px] text-xs font-medium leading-[14px] text-ink-2 lg:text-sm" aria-live="polite">
            <span className="size-[7px] rounded-full" style={{ background: dot }} />
            {t(label)}
          </span>
        </div>
        <div className="flex-1" />
        {!pwa.isStandalone() && (
          <button type="button" onClick={() => openSheet("install")}
            className="hidden items-center gap-1.5 px-3 font-semibold text-primary lg:flex">
            <Icon name="install_desktop" size={22} /> {t("menuInstall")}
          </button>
        )}
        <button type="button" aria-label={t("menu")} onClick={() => openSheet("menu")}
          className="flex size-11 items-center justify-center rounded-xl text-ink hover:bg-surface-2">
          <Icon name="menu" />
        </button>
      </div>
      {progress && (
        <div className="flex flex-col gap-1.5 px-[18px] pb-2.5 pt-0.5 lg:mx-auto lg:w-full lg:max-w-[720px]">
          <div className="flex justify-between text-[13px] font-medium text-ink-2">
            <span>{t("needsProgress")}</span>
            <span>{progress.step} {t("of")} {progress.total}</span>
          </div>
          <div className="h-1 overflow-hidden rounded-sm bg-line" role="progressbar" aria-valuemin={0}
            aria-valuemax={progress.total} aria-valuenow={progress.step}>
            <div className={cn("h-1 rounded-sm bg-primary transition-[width] duration-300")}
              style={{ width: `${Math.round((progress.step / progress.total) * 100)}%` }} />
          </div>
        </div>
      )}
    </header>
  );
}
