import type { Citation } from "@sahaj/contracts";
import { Headset, Play, Share } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { CardView } from "@/components/conversation/CardView";
import { RichText } from "@/components/conversation/RichText";
import { TalkButton } from "@/components/conversation/TalkButton";
import { Button } from "@/components/ui/button";
import { Drawer, DrawerContent, DrawerDescription, DrawerFooter, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import { answerConsent, replay, requestHuman, reviewConsent } from "@/lib/session";
import { cn } from "@/lib/utils";
import { pwa } from "@/pwa";
import { useSession, type TimelineItem } from "@/store/session";

/**
 * Temporary functional UI so the full flow (consent, voice, cards, citations, handoff, reconnects) can be
 * tested on real phones before the designs land. Replace screen by screen; the store and controller stay.
 */
export function App() {
  const timeline = useSession((s) => s.timeline);
  const handoff = useSession((s) => s.handoff);
  const consent = useSession((s) => s.consent.conversation);
  const [citation, setCitation] = useState<Citation | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => end.current?.scrollIntoView({ behavior: "smooth", block: "end" }), [timeline.length]);

  return (
    <div className="flex h-full flex-col">
      <Header />
      <main className="px-safe flex-1 overflow-y-auto py-4">
        <div className="mx-auto flex max-w-2xl flex-col gap-3">
          {timeline.length === 0 && <Welcome />}
          {timeline.map((item) => <Item key={item.id} item={item} onCite={setCitation} />)}
          {consent === "revoked" && !handoff && (
            <div className="rounded-xl border p-4 text-sm">
              Nothing is processed without your consent.
              <Button variant="link" className="px-1" onClick={reviewConsent}>Review consent</Button>
            </div>
          )}
          <div ref={end} />
        </div>
      </main>
      {handoff ? <HandoffPanel reference={handoff.reference} /> : <Dock />}
      <MicHelp />
      <ConsentSheet />
      <Drawer open={!!citation} onOpenChange={(o) => !o && setCitation(null)}>
        <DrawerContent>
          <DrawerHeader>
            <DrawerTitle>Source · {citation?.id}</DrawerTitle>
            <DrawerDescription className="max-h-[50vh] overflow-y-auto whitespace-pre-wrap text-left text-foreground">
              {citation?.text}
            </DrawerDescription>
          </DrawerHeader>
        </DrawerContent>
      </Drawer>
    </div>
  );
}

function Header() {
  const connection = useSession((s) => s.connection);
  const dot = { open: "bg-emerald-500", connecting: "bg-amber-400", reconnecting: "bg-amber-400", offline: "bg-red-500" }[connection];
  return (
    <header className="pt-safe px-safe border-b bg-background/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-2xl items-center justify-between">
        <span className="text-lg font-semibold text-primary">Sahaj</span>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="rounded-full bg-accent/30 px-2 py-0.5 font-medium text-foreground">Sample data</span>
          <span className="flex items-center gap-1.5"><span className={cn("size-2 rounded-full", dot)} />{connection}</span>
        </div>
      </div>
    </header>
  );
}

function Welcome() {
  const [showIOSInstall] = useState(() => pwa.isIOS() && !pwa.isStandalone());
  return (
    <div className="py-6 text-center">
      <h1 className="text-2xl font-semibold">Ask about insurance or loans</h1>
      <p className="mt-2 text-muted-foreground">Hold the button and speak in your language. Try saying:</p>
      <ul className="mt-4 space-y-2 text-sm">
        {["What is the waiting period for pre-existing diseases?", "Compare the Lotus and Neem health plans",
          "Which health insurance should I buy for my family?", "What would the EMI be on 5 lakh at 11% for 3 years?",
          "टर्म इंश्योरेंस और होल लाइफ में क्या फर्क है?"].map((t) => (
          <li key={t} className="rounded-full border px-4 py-2">“{t}”</li>
        ))}
      </ul>
      {showIOSInstall && (
        <p className="mt-6 flex items-center justify-center gap-1 text-xs text-muted-foreground">
          Install: tap <Share className="size-3.5" /> then “Add to Home Screen”
        </p>
      )}
    </div>
  );
}

function Item({ item, onCite }: { item: TimelineItem; onCite: (c: Citation) => void }) {
  switch (item.kind) {
    case "user":
      return <div className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-primary-foreground"><RichText text={item.text} /></div>;
    case "assistant":
      return (
        <div className="max-w-[90%] rounded-2xl rounded-bl-sm border bg-card px-4 py-3">
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-primary">{item.agent}</p>
          <p className="leading-relaxed"><RichText text={item.text} citations={item.citations} onCite={onCite} /></p>
          <div className="mt-2 flex gap-2">
            {item.audioUrl && (
              <Button size="sm" variant="ghost" className="h-8 px-2" onClick={() => replay(item.audioUrl!)}>
                <Play className="size-4" /> Replay
              </Button>
            )}
            <Button size="sm" variant="ghost" className="h-8 px-2" onClick={requestHuman}>
              <Headset className="size-4" /> Talk to a human
            </Button>
          </div>
        </div>
      );
    case "card":
      return <CardView card={item.card} />;
    case "system":
      return <p className="text-center text-xs text-muted-foreground">{item.text}</p>;
    case "error":
      return <p className="rounded-lg bg-destructive/10 px-3 py-2 text-center text-sm text-destructive">{item.text}</p>;
  }
}

function Dock() {
  return (
    <footer className="pb-safe px-safe border-t bg-background pt-3">
      <div className="mx-auto flex max-w-2xl items-end justify-between">
        <span className="w-24" />
        <TalkButton />
        <Button variant="ghost" className="w-24 flex-col gap-1 text-xs" onClick={requestHuman}>
          <Headset className="size-5" /> Human
        </Button>
      </div>
    </footer>
  );
}

function HandoffPanel({ reference }: { reference: string }) {
  return (
    <footer className="pb-safe px-safe border-t bg-secondary pt-4 text-center">
      <p className="font-medium">A person will take it from here</p>
      <p className="mt-1 text-sm text-muted-foreground">Your reference</p>
      <p className="select-all text-2xl font-semibold tracking-wider">{reference}</p>
    </footer>
  );
}

function ConsentSheet() {
  const prompt = useSession((s) => s.consentPrompt);
  return (
    <Drawer open={!!prompt} dismissible={false}>
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle>{prompt?.purpose === "needs_analysis" ? "Use your details?" : "Before we start"}</DrawerTitle>
          <DrawerDescription className="max-h-[50vh] overflow-y-auto whitespace-pre-wrap text-left text-foreground">
            {prompt?.text}
          </DrawerDescription>
          <p className="text-left text-[11px] text-muted-foreground">Version {prompt?.version}</p>
        </DrawerHeader>
        <DrawerFooter className="pb-safe grid grid-cols-2 gap-3">
          <Button variant="outline" size="lg" onClick={() => answerConsent(false)}>Not now</Button>
          <Button size="lg" onClick={() => answerConsent(true)}>I agree</Button>
        </DrawerFooter>
      </DrawerContent>
    </Drawer>
  );
}

function MicHelp() {
  const error = useSession((s) => s.micError);
  if (!error) return null;
  const text = {
    insecure: "The microphone only works over HTTPS. Open the https:// link (see the README).",
    denied: pwa.isIOS()
      ? "Microphone access is blocked. Go to Settings → Safari → Microphone (or tap “aA” → Website Settings) and allow it."
      : "Microphone access is blocked. Allow it in your browser's site settings, then try again.",
    "no-device": "No microphone was found.",
    unsupported: "This browser can't record audio. Please use Safari or Chrome.",
    unknown: "The microphone couldn't be opened. Please try again.",
  }[error];
  return <div className="px-safe fixed inset-x-0 top-16 z-40 mx-auto max-w-2xl"><p className="rounded-lg bg-destructive px-4 py-3 text-sm text-white shadow-lg">{text}</p></div>;
}
