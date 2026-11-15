import { AnimatePresence, motion } from "motion/react";
import { memo, useEffect, useRef, useState } from "react";
import { CardSummary, CardView } from "@/components/cards/card-view";
import { HandoffCard, NeedsConsentCard } from "@/components/cards/advice";
import { KycCard } from "@/components/cards/kyc";
import { InstallCard } from "@/components/sheets/info-sheets";
import { Icon } from "@/components/ui/icon";
import { useIsDesktop } from "@/lib/media";
import { useT } from "@/lib/i18n";
import { clean, cn, withRupeeSign } from "@/lib/utils";
import { canTalk, kycCase, useSession, type TimelineItem } from "@/store/session";
import { RichText } from "./rich-text";
import {
  AgentMessage, AssistantBubble, ListeningBubble, openCitation, ResetNote, Rise, Suggestions, SystemNote, ThinkingBubble,
  UserBubble,
} from "./messages";
import { ConsentDeclined, Welcome } from "./welcome";

export function Timeline() {
  const t = useT();
  const timeline = useSession((s) => s.timeline);
  const turn = useSession((s) => s.turn);
  // Once the answer's text is on screen it stands in for the "working on it" bubble (the dock still shows progress).
  const working = useSession((s) => (s.turn === "sending" || s.turn === "thinking") && !s.replied);
  const canAsk = useSession((s) => canTalk(s) && s.turn === "idle");
  const handoff = useSession((s) => s.handoff);
  const kyc = useSession((s) => !!kycCase(s));
  const declined = useSession((s) => s.declined && s.consent.conversation.state !== "granted" && !s.consentPrompt);
  const scroller = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const latest = [...timeline].reverse().find((i) => i.kind === "assistant");
  const lastAssistant = latest?.id;
  // follow-ups only while the latest reply is the last thing said
  const suggestions = latest?.kind === "assistant" && timeline[timeline.length - 1]?.id === latest.id ? latest.suggestions : [];
  const conversationItems = timeline.some((i) => i.kind !== "system");

  // Follow the conversation while the person is at the bottom; otherwise offer "Jump to latest".
  // "At the bottom" only ends when the person scrolls up: our own smooth scroll passes through positions far from the
  // bottom, and must not count as leaving it (that made the button flash and stopped the follow halfway).
  const following = useRef(true);
  const follows = conversationItems; // the welcome screen reads from the top
  useEffect(() => {
    const el = scroller.current;
    const inner = content.current;
    if (!el || !inner) return;
    let lastTop = el.scrollTop;
    const pin = (value: boolean) => {
      following.current = value;
      setAtBottom(value);
    };
    const onScroll = () => {
      const top = el.scrollTop;
      if (el.scrollHeight - top - el.clientHeight < 80) pin(true);
      else if (top < lastTop - 2) pin(false);
      lastTop = top;
    };
    const toBottom = () => {
      if (follows && following.current) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    // Any growth counts, not only new messages: a status step, the replay button, follow-up chips.
    const observer = new ResizeObserver(toBottom);
    observer.observe(inner);
    toBottom();
    return () => {
      el.removeEventListener("scroll", onScroll);
      observer.disconnect();
    };
  }, [follows]);
  // A handoff always comes into view: it carries the reference number.
  useEffect(() => {
    if (!handoff) return;
    following.current = true;
    setAtBottom(true);
    const id = setTimeout(() => scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" }), 50);
    return () => clearTimeout(id);
  }, [handoff]);

  if (declined && !conversationItems) return <ConsentDeclined />;

  return (
    <div className="relative min-h-0 flex-1">
      <div ref={scroller} className="scrollbar-none h-full overflow-y-auto overscroll-contain">
        <div ref={content} className={cn("px-gutter mx-auto flex min-h-full max-w-[720px] flex-col gap-4 py-4", conversationItems && "justify-end")}>
          {!conversationItems && <Welcome />}
          {timeline.map((item) => (
            <Rise key={item.id} from={item.kind === "user" ? "person" : "sahaj"}><Item item={item} isLatest={item.id === lastAssistant} /></Rise>
          ))}
          {(turn === "recording" || turn === "starting") && <Rise from="person"><ListeningBubble /></Rise>}
          {working && <Rise><ThinkingBubble /></Rise>}
          {handoff && (
            <Rise>
              {kyc ? <KycCard handoff={handoff} />
                : <HandoffCard reference={handoff.reference} reason={handoff.reason} agentName={handoff.agentName} />}
            </Rise>
          )}
          {!handoff && canAsk && suggestions.length > 0 && <Rise><Suggestions items={suggestions} /></Rise>}
          {turn === "idle" && !handoff && <InstallCard />}
        </div>
      </div>
      <AnimatePresence>
        {!atBottom && (
          <motion.button type="button" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }}
            onClick={() => {
              following.current = true;
              setAtBottom(true);
              scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
            }}
            className="absolute bottom-3 left-1/2 flex h-11 -translate-x-1/2 items-center gap-2 rounded-full bg-toast px-4 text-[15px] font-semibold text-toast-ink shadow-raised">
            <Icon name="arrow_downward" size={20} /> {t("jumpLatest")}
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}

/** Memoised: a message is drawn again only when it changes, not on every step of the turn. */
const Item = memo(function Item({ item, isLatest }: { item: TimelineItem; isLatest: boolean }) {
  const desktop = useIsDesktop();
  switch (item.kind) {
    case "user":
      return <UserBubble><RichText text={item.text} inverse /></UserBubble>;
    case "assistant":
      return (
        <AssistantBubble item={item} isLatest={isLatest}>
          <RichText text={withRupeeSign(clean(item.text))} citations={item.citations} onCite={(id) => openCitation(item.id, id)} />
        </AssistantBubble>
      );
    case "card":
      return desktop ? <CardSummary card={item.card} itemId={item.id} /> : <CardView card={item.card} />;
    case "consent":
      return <NeedsConsentCard prompt={item.prompt} answered={item.answered} />;
    case "system":
      return <SystemNote icon={item.icon} text={item.text} tone={item.tone} vars={item.vars} />;
    case "agent":
      return <AgentMessage name={item.name} text={item.text} />;
    case "reset":
      return <ResetNote />;
  }
});
