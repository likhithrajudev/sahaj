import { useEffect } from "react";
import { CardView } from "@/components/cards/card-view";
import { Dock } from "@/components/conversation/dock";
import { Timeline } from "@/components/conversation/timeline";
import { ConnectionBanner } from "@/components/layout/connection-banner";
import { Header } from "@/components/layout/header";
import { Splash } from "@/components/layout/splash";
import { CitationSheet } from "@/components/sheets/citation-sheet";
import { ConsentSheet } from "@/components/sheets/consent-sheet";
import { AboutSheet, InstallSheet } from "@/components/sheets/info-sheets";
import { MenuSheet, WithdrawDialog } from "@/components/sheets/menu-sheet";
import { MicSheet } from "@/components/sheets/mic-sheet";
import { Icon } from "@/components/ui/icon";
import { useT } from "@/lib/i18n";
import { useIsDesktop } from "@/lib/media";
import { pwa } from "@/pwa";
import { latestCard, useSession } from "@/store/session";
import { openSheet, useUi } from "@/store/ui";

export function App() {
  const desktop = useIsDesktop();
  useOfferInstall(desktop);
  return (
    <div className="flex h-full flex-col bg-bg">
      <Header />
      <ConnectionBanner />
      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col">
          <Timeline />
          <Dock />
        </main>
        {desktop && <CardPanel />}
      </div>
      <ConsentSheet />
      <CitationSheet />
      <MicSheet />
      <MenuSheet />
      <InstallSheet />
      <AboutSheet />
      <WithdrawDialog />
      <Splash />
    </div>
  );
}

/** Desktop: the newest card (or the one opened from the timeline) in full, beside the conversation. */
function CardPanel() {
  const t = useT();
  const latest = useSession(latestCard);
  const panelId = useUi((s) => s.panelItemId);
  const open = useUi((s) => s.panelOpen);
  const chosen = useSession((s) => s.timeline.find((i) => i.id === panelId));
  const item = chosen?.kind === "card" ? chosen : latest;
  if (!item || !open) return null;
  return (
    <aside className="scrollbar-none w-[500px] flex-none overflow-y-auto border-l border-line bg-bg px-6 pb-8 pt-6" aria-label={t("latestCard")}>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-[.12em] text-ink-2">{t("latestCard")}</h2>
        <button type="button" aria-label={t("close")} onClick={() => useUi.setState({ panelOpen: false })}
          className="flex size-10 items-center justify-center rounded-xl text-ink-2 hover:bg-surface-2">
          <Icon name="close" />
        </button>
      </div>
      <CardView key={item.id} card={item.card} />
    </aside>
  );
}

/** Offer "Add to home screen" once, after the first answer (never on first load). */
function useOfferInstall(desktop: boolean) {
  const answered = useSession((s) => s.timeline.some((i) => i.kind === "assistant"));
  const idle = useSession((s) => s.turn === "idle");
  useEffect(() => {
    const ui = useUi.getState();
    if (!answered || !idle || desktop || ui.installDismissed || ui.sheet || pwa.isStandalone()) return;
    if (pwa.canPrompt()) return void useUi.setState({ installCard: true }); // Android: inline card
    if (!pwa.isIOS()) return;
    const id = setTimeout(() => { // iOS has no prompt: the "Add to Home Screen" steps
      if (!useUi.getState().sheet && useSession.getState().turn === "idle") openSheet("install");
    }, 1500);
    return () => clearTimeout(id);
  }, [answered, idle, desktop]);
}
