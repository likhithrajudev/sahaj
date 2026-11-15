import type { ReactNode } from "react";
import { Drawer as Vaul } from "vaul";
import { cn } from "@/lib/utils";

/**
 * Bottom sheet (Sheets motion: up 320 ms, scrim 45%, drag the handle to dismiss). On wide screens it becomes a
 * centred dialog. `dismissible={false}` for decisions that need an explicit answer (consent).
 */
export function Sheet({ open, onClose, dismissible = true, label, children, className }: {
  open: boolean; onClose?: () => void; dismissible?: boolean; label: string; children: ReactNode; className?: string;
}) {
  return (
    <Vaul.Root open={open} onOpenChange={(o) => !o && onClose?.()} dismissible={dismissible} repositionInputs={false}>
      <Vaul.Portal>
        <Vaul.Overlay className="fixed inset-0 z-40" style={{ background: "var(--scrim)" }} />
        <Vaul.Content
          aria-describedby={undefined}
          className={cn(
            "fixed inset-x-0 bottom-0 z-50 mx-auto flex max-h-[92dvh] w-full max-w-[560px] flex-col rounded-t-[28px] bg-surface text-ink outline-none",
            "shadow-sheet md:bottom-auto md:top-1/2 md:max-h-[85dvh] md:-translate-y-1/2 md:rounded-[28px] md:after:hidden!",
            className,
          )}
        >
          <Vaul.Title className="sr-only">{label}</Vaul.Title>
          <div className="mx-auto mt-2.5 mb-1 h-[5px] w-10 flex-none rounded-full bg-line-2 md:hidden" aria-hidden />
          <div className="pb-safe flex min-h-0 flex-1 flex-col overflow-y-auto px-6 pt-3">{children}</div>
        </Vaul.Content>
      </Vaul.Portal>
    </Vaul.Root>
  );
}
