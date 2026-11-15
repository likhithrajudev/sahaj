import { useRef, type ReactNode } from "react";
import { Drawer as Vaul } from "vaul";
import { cn } from "@/lib/utils";
import { useSheet, type Sheet as SheetName } from "@/store/ui";

/**
 * Bottom sheet (Sheets motion: up 320 ms, scrim 45%, drag the handle to dismiss). On wide screens it becomes a
 * centred dialog. `dismissible={false}` for decisions that need an explicit answer (consent).
 *
 * Pass `name` for a sheet in the ui store: a sheet opened on top of it leaves it open underneath (it steps back),
 * and closing the top one brings it forward again. Pass `open` for one driven by other state.
 */
export function Sheet({ name, open: openProp, onClose, dismissible = true, label, children, className }: {
  name?: Exclude<SheetName, null>; open?: boolean; onClose?: () => void; dismissible?: boolean; label: string;
  children: ReactNode; className?: string;
}) {
  const stacked = useSheet(name ?? "menu");
  const open = name ? stacked.open : !!openProp;
  const behind = !!name && stacked.behind;
  // What it showed while open stays on screen while it slides away, even if the state behind it has been cleared.
  const shown = useRef(children);
  // On top of another sheet, whose scrim already darkens the page; kept while closing so the scrim doesn't flash.
  const over = useRef(false);
  if (open) {
    shown.current = children;
    over.current = !!name && stacked.over;
  }

  return (
    <Vaul.Root open={open} onOpenChange={(o) => !o && onClose?.()} dismissible={dismissible && !behind} repositionInputs={false}>
      <Vaul.Portal>
        <Vaul.Overlay className="sheet-overlay fixed inset-0 z-40" style={{ background: over.current ? "var(--scrim-stacked)" : "var(--scrim)" }} />
        <Vaul.Content
          aria-describedby={undefined}
          data-behind={behind || undefined}
          className={cn(
            "sheet fixed inset-x-0 bottom-0 z-50 mx-auto flex max-h-[92dvh] w-full max-w-[560px] flex-col rounded-t-[28px] bg-surface text-ink outline-none",
            "shadow-sheet md:bottom-auto md:top-1/2 md:max-h-[85dvh] md:-translate-y-1/2 md:rounded-[28px] md:after:hidden!",
            className,
          )}
        >
          <Vaul.Title className="sr-only">{label}</Vaul.Title>
          <div className="mx-auto mb-1 mt-2.5 h-[5px] w-11 flex-none rounded-full bg-line-2 md:hidden" aria-hidden />
          <div className="pb-safe flex min-h-0 flex-1 flex-col overflow-y-auto px-6 pt-3">{open ? children : shown.current}</div>
        </Vaul.Content>
      </Vaul.Portal>
    </Vaul.Root>
  );
}
