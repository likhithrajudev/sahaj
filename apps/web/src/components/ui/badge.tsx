import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Icon } from "./icon";

const TONES = {
  warm: "bg-warm-soft text-warm-ink",
  neutral: "bg-surface-2 text-ink-2",
  info: "bg-info-soft text-info",
  success: "bg-success-soft text-success",
  insurance: "bg-primary-soft text-primary",
  loan: "bg-loan-soft text-loan",
  general: "bg-surface-2 text-ink-2",
  dark: "bg-toast text-toast-ink",
} as const;

export function Badge({ tone = "neutral", icon, children, className }: {
  tone?: keyof typeof TONES; icon?: string; children: ReactNode; className?: string;
}) {
  return (
    <span className={cn("inline-flex h-6 items-center gap-1 whitespace-nowrap rounded-full px-[9px] text-xs font-semibold", TONES[tone], className)}>
      {icon && <Icon name={icon} size={15} />}
      {children}
    </span>
  );
}
