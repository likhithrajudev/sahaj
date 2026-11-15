import type { ReactNode } from "react";
import { Icon } from "@/components/ui/icon";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export function CardShell({ icon, iconClass, title, badges, children, className, flush }: {
  icon: string; iconClass?: string; title: ReactNode; badges?: ReactNode; children: ReactNode; className?: string; flush?: boolean;
}) {
  return (
    <section className={cn("card overflow-hidden", className)}>
      <header className="flex flex-wrap items-center gap-x-2.5 gap-y-2 px-[18px] pt-4">
        <span className={cn("flex size-8 flex-none items-center justify-center rounded-[10px]", iconClass ?? "bg-primary-soft text-primary")}>
          <Icon name={icon} size={19} />
        </span>
        <h3 className="flex-1 text-base font-semibold">{title}</h3>
        {badges && <span className="flex flex-wrap gap-1.5">{badges}</span>}
      </header>
      <div className={flush ? "pt-3" : "px-[18px] pb-[18px] pt-4"}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, className }: { label: string; value: ReactNode; className?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-0.5", className)}>
      <span className="text-[13px] text-ink-3">{label}</span>
      <span className="text-[17px] font-semibold leading-6 tabular-nums">{value}</span>
    </div>
  );
}

export function LenderNote() {
  const t = useT();
  return <p className="mt-4 text-[13px] leading-[18px] text-ink-3">{t("lenderNote")}</p>;
}
