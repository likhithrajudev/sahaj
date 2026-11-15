import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { SignIn } from "@/components/auth/sign-in";
import { CardView } from "@/components/cards/card-view";
import { Dock } from "@/components/conversation/dock";
import { Timeline } from "@/components/conversation/timeline";
import { ConnectionBanner } from "@/components/layout/connection-banner";
import { Header } from "@/components/layout/header";
import { Splash } from "@/components/layout/splash";
import { DocumentScopeBar, JourneySheet, PolicyDocumentsSheet } from "@/components/sheets/document-workflows";
import { CitationSheet } from "@/components/sheets/citation-sheet";
import { previewScene, seedPreview } from "@/dev/preview";
import { ConsentSheet } from "@/components/sheets/consent-sheet";
import { AboutSheet, InstallSheet, TrustSheet } from "@/components/sheets/info-sheets";
import { KycSheet } from "@/components/sheets/kyc-sheet";
import { MenuSheet, WithdrawDialog } from "@/components/sheets/menu-sheet";
import { MicSheet } from "@/components/sheets/mic-sheet";
import { Icon } from "@/components/ui/icon";
import { useT } from "@/lib/i18n";
import { signOut, useAuth } from "@/lib/auth";
import { useIsDesktop } from "@/lib/media";
import { connect, disconnect } from "@/lib/session";
import { pwa } from "@/pwa";
import { latestCard, useSession } from "@/store/session";
import { openSheet, useUi } from "@/store/ui";

const preview = import.meta.env.DEV ? previewScene() : null;
if (preview) seedPreview(preview);

/** Signed out: the sign-in screen. Signed in: the conversation, connected with the account's token. */
export function App() {
  if (preview === "signin") return <SignIn />;
  if (preview) return <Conversation />;
  return <Live />;
}

function Live() {
  const signedIn = useAuth((s) => !!s.refreshToken);
  const lost = useSession((s) => s.connection === "signed_out");
  const [ended, setEnded] = useState(false);

  useEffect(() => {
    if (!signedIn) return;
    setEnded(false);
    connect();
    return () => disconnect();
  }, [signedIn]);

  // the server rejected the session (refresh token expired, revoked or reused): back to sign-in
  useEffect(() => {
    if (signedIn && lost) {
      setEnded(true);
      void signOut();
    }
  }, [signedIn, lost]);

  if (!signedIn) return <SignIn ended={ended} />;
  return <Conversation />;
}

function Conversation() {
  const desktop = useIsDesktop();
  useOfferInstall(desktop);
  return (
    <div className="flex h-full flex-col bg-bg" style={{ backgroundImage: "var(--wash)" }}>
      <Header />
      <ConnectionBanner />
      <DocumentScopeBar />
      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col">
          <Timeline />
          <Dock />
        </main>
        {desktop && <CardPanel />}
      </div>
      <ConsentSheet />
      <CitationSheet />
      <PolicyDocumentsSheet />
      <JourneySheet kind="claim" />
      <JourneySheet kind="loan" />
      <MicSheet />
      <MenuSheet />
      <InstallSheet />
      <AboutSheet />
      <TrustSheet />
      <KycSheet />
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
    <aside className="scrollbar-none w-[500px] flex-none overflow-y-auto border-l border-line bg-surface-muted px-6 pb-8 pt-5" aria-label={t("latestCard")}>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-[17px] font-semibold text-ink">{t("latestCard")}</h2>
        <button type="button" aria-label={t("close")} onClick={() => useUi.setState({ panelOpen: false })}
          className="flex size-10 items-center justify-center rounded-full text-ink-2 transition-colors hover:bg-surface-2">
          <Icon name="close" />
        </button>
      </div>
      <motion.div key={item.id} initial={{ opacity: 0, x: 16, filter: "blur(6px)" }} animate={{ opacity: 1, x: 0, filter: "blur(0px)" }}
        transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}>
        <CardView card={item.card} />
      </motion.div>
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
