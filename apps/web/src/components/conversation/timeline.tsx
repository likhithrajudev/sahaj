import { AnimatePresence, motion } from "motion/react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { CardSummary, CardView } from "@/components/cards/card-view";
import { HandoffCard, NeedsConsentCard } from "@/components/cards/advice";
import { InstallCard } from "@/components/sheets/info-sheets";
import { Icon } from "@/components/ui/icon";
import { useIsDesktop } from "@/lib/media";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { useSession, type TimelineItem } from "@/store/session";
import { RichText } from "./rich-text";
import {
  AssistantBubble, ListeningBubble, openCitation, ResetNote, Rise, SystemNote, ThinkingBubble, UserBubble,
} from "./messages";
import { ConsentDeclined, Welcome } from "./welcome";

export function Timeline() {
  const t = useT();
  const timeline = useSession((s) => s.timeline);
  const turn = useSession((s) => s.turn);
  const handoff = useSession((s) => s.handoff);
  const declined = useSession((s) => s.declined && s.consent.conversation.state !== "granted" && !s.consentPrompt);
  const scroller = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const lastAssistant = [...timeline].reverse().find((i) => i.kind === "assistant")?.id;
  const conversationItems = timeline.some((i) => i.kind !== "system");

  // Follow new content while the person is at the bottom; otherwise offer "Jump to latest".
  useLayoutEffect(() => {
    if (!conversationItems) return; // the welcome screen reads from the top
    if (atBottom) scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [timeline.length, turn, handoff, atBottom, conversationItems]);
  // A handoff always comes into view: it carries the reference number.
  useEffect(() => {
    if (handoff) setTimeout(() => scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" }), 50);
  }, [handoff]);
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const onScroll = () => setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  if (declined && !conversationItems) return <ConsentDeclined />;

  return (
    <div className="relative min-h-0 flex-1">
      <div ref={scroller} className="scrollbar-none h-full overflow-y-auto overscroll-contain">
        <div className={cn("px-gutter mx-auto flex min-h-full max-w-[720px] flex-col gap-3.5 py-4", conversationItems && "justify-end")}>
          {!conversationItems && <Welcome />}
          {timeline.map((item) => (
            <Rise key={item.id}><Item item={item} isLatest={item.id === lastAssistant} /></Rise>
          ))}
          {(turn === "recording" || turn === "starting") && <Rise><ListeningBubble /></Rise>}
          {(turn === "sending" || turn === "thinking") && <Rise><ThinkingBubble /></Rise>}
          {handoff && <Rise><HandoffCard reference={handoff.reference} reason={handoff.reason} /></Rise>}
          {turn === "idle" && !handoff && <InstallCard />}
        </div>
      </div>
      <AnimatePresence>
        {!atBottom && (
          <motion.button type="button" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }}
            onClick={() => scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" })}
            className="absolute bottom-3 right-4 flex h-11 items-center gap-2 rounded-full bg-toast px-4 text-[15px] font-semibold text-toast-ink shadow-lg">
            <Icon name="arrow_downward" size={20} /> {t("jumpLatest")}
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}

function Item({ item, isLatest }: { item: TimelineItem; isLatest: boolean }) {
  const desktop = useIsDesktop();
  switch (item.kind) {
    case "user":
      return <UserBubble><RichText text={item.text} inverse /></UserBubble>;
    case "assistant":
      return (
        <AssistantBubble item={item} isLatest={isLatest}>
          <RichText text={item.text} citations={item.citations} onCite={(id) => openCitation(item.id, id)} />
        </AssistantBubble>
      );
    case "card":
      return desktop ? <CardSummary card={item.card} itemId={item.id} /> : <CardView card={item.card} />;
    case "consent":
      return <NeedsConsentCard prompt={item.prompt} answered={item.answered} />;
    case "system":
      return <SystemNote icon={item.icon} text={item.text} tone={item.tone} />;
    case "reset":
      return <ResetNote />;
  }
}
