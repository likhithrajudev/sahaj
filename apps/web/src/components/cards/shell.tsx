import type { ReactNode } from "react";
import { Icon } from "@/components/ui/icon";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export function CardShell({ icon, iconClass, title, children, className, flush }: {
  icon: string; iconClass?: string; title: ReactNode; children: ReactNode; className?: string; flush?: boolean;
}) {
  return (
    <section className={cn("overflow-hidden rounded-[20px] border border-line bg-surface", className)}>
      <header className="flex items-center gap-2 px-[18px] pt-[18px]">
        <Icon name={icon} size={20} className={iconClass ?? "text-primary"} />
        <h3 className="flex-1 text-[15px] font-semibold">{title}</h3>
      </header>
      <div className={flush ? "pt-3" : "px-[18px] pb-[18px] pt-3.5"}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, className }: { label: string; value: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-0.5", className)}>
      <span className="text-[13px] text-ink-3">{label}</span>
      <span className="text-[17px] font-semibold leading-6">{value}</span>
    </div>
  );
}

export function LenderNote() {
  const t = useT();
  return <p className="mt-3 text-[13px] leading-[18px] text-ink-3">{t("lenderNote")}</p>;
}
