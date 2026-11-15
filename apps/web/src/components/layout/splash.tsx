import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { VoiceBars } from "@/components/brand/voice-bars";
import { useT } from "@/lib/i18n";
import { useSession } from "@/store/session";

/** Launch screen while the first connection opens. Never blocks for more than a few seconds. */
export function Splash() {
  const t = useT();
  const ready = useSession((s) => s.connection === "open" || s.connection === "offline");
  const [timedOut, setTimedOut] = useState(false);
  useEffect(() => {
    const id = setTimeout(() => setTimedOut(true), 4000);
    return () => clearTimeout(id);
  }, []);
  const show = !ready && !timedOut;

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          key="splash"
          initial={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.25 } }}
          className="fixed inset-0 z-[60] flex flex-col items-center justify-center text-white"
          style={{ background: "var(--hero)" }}
        >
          <VoiceBars mode="thinking" height={88} tone="inverse" />
          <h1 className="mt-8 text-[48px] font-bold leading-none tracking-[-0.025em]">Sahaj</h1>
          <p className="mt-3 max-w-[260px] text-center text-[17px] leading-6 text-white/85">{t("tagline")}</p>
          <span className="absolute bottom-[calc(env(safe-area-inset-bottom)+56px)] text-sm text-white/80">{t("connectingSecurely")}</span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
