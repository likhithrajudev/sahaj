import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { LogoBars } from "@/components/brand/logo";
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
          className="fixed inset-0 z-[60] flex flex-col items-center justify-center bg-[var(--brand-action)] text-white"
        >
          <LogoBars height={88} tone="inverse" />
          <h1 className="mt-7 text-[44px] font-bold leading-none tracking-[-0.025em]">Sahaj</h1>
          <p className="mt-3 max-w-[260px] text-center text-[17px] leading-6 text-white/85">{t("tagline")}</p>
          <div className="absolute bottom-[calc(env(safe-area-inset-bottom)+64px)] flex flex-col items-center gap-3">
            <div className="h-[3px] w-[120px] overflow-hidden rounded-full bg-white/20">
              <motion.div className="h-full w-2/5 rounded-full bg-accent"
                animate={{ x: ["-100%", "250%"] }} transition={{ repeat: Infinity, duration: 1.4, ease: "easeInOut" }} />
            </div>
            <span className="text-sm text-white/85">{t("connectingSecurely")}</span>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
