import { useQuery } from "@tanstack/react-query";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { VoiceBars } from "@/components/brand/voice-bars";
import { EXAMPLES } from "@/components/conversation/welcome";
import { Icon } from "@/components/ui/icon";
import { getAuthConfig, signInWithGoogle } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { useUi } from "@/store/ui";

/** Google Identity Services (loaded only when the server has a Google client id). */
type Gis = {
  accounts: {
    id: {
      initialize: (o: { client_id: string; callback: (r: { credential: string }) => void; ux_mode?: string }) => void;
      renderButton: (el: HTMLElement, o: Record<string, unknown>) => void;
    };
  };
};

function loadGis(): Promise<Gis> {
  const w = window as unknown as { google?: Gis };
  if (w.google?.accounts?.id) return Promise.resolve(w.google);
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = () => (w.google ? resolve(w.google) : reject(new Error("Google sign-in did not load")));
    s.onerror = () => reject(new Error("Google sign-in did not load"));
    document.head.appendChild(s);
  });
}

export function SignIn({ ended }: { ended?: boolean }) {
  const t = useT();
  const config = useQuery({ queryKey: ["auth-config"], queryFn: getAuthConfig, retry: 1 });
  const [error, setError] = useState<string | null>(ended ? t("sessionEnded") : null);
  const [busy, setBusy] = useState(false);

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const nothing = config.data && !config.data.google_client_id;
  const reduce = useReducedMotion();
  // The bars say hello once, then settle into the logo.
  const [greeting, setGreeting] = useState(!reduce);
  useEffect(() => {
    const id = setTimeout(() => setGreeting(false), 2600);
    return () => clearTimeout(id);
  }, []);

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-bg lg:grid lg:grid-cols-[1.1fr_1fr]" style={{ backgroundImage: "var(--wash)" }}>
      <section className="pt-safe relative flex flex-none flex-col overflow-hidden rounded-b-[32px] text-white lg:m-4 lg:rounded-[32px]"
        style={{ background: "var(--hero)" }}>
        <div className="px-gutter mx-auto flex w-full max-w-[440px] flex-col items-center gap-4 pb-12 pt-14 text-center lg:mx-0 lg:mt-auto lg:max-w-[560px] lg:items-start lg:px-14 lg:pb-14 lg:text-left">
          <motion.div initial={reduce ? false : { opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}>
            <VoiceBars mode={greeting ? "speaking" : "still"} height={64} tone="inverse" />
          </motion.div>
          <motion.div initial={reduce ? false : { opacity: 0, y: 8, filter: "blur(6px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            transition={{ delay: 0.15, duration: 0.6, ease: [0.16, 1, 0.3, 1] }}>
            <p className="text-[48px] font-bold leading-none tracking-[-0.025em] lg:text-[64px]">Sahaj</p>
            <p className="mt-3 text-[17px] leading-6 text-white/85 lg:text-[20px] lg:leading-7">{t("tagline")}</p>
          </motion.div>
          <ul className="mt-8 hidden flex-col gap-2.5 lg:flex">
            {EXAMPLES.slice(0, 3).concat(EXAMPLES.slice(-1)).map((e, i) => (
              <motion.li key={e.text} lang={e.lang}
                initial={reduce ? false : { opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.5 + i * 0.12, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
                className="w-fit rounded-[20px] rounded-bl-md bg-white/10 px-4 py-2.5 text-[17px] leading-6 text-white/95">
                “{e.text}”
              </motion.li>
            ))}
          </ul>
        </div>
      </section>

      <div className="pb-safe px-gutter mx-auto -mt-6 flex w-full max-w-[460px] flex-1 flex-col gap-6 pb-8 lg:mt-0 lg:justify-center lg:py-10">
        <motion.section initial={reduce ? false : { opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.25, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
          className="card flex flex-col gap-5 p-6 lg:shadow-raised">
          <div>
            <h1 className="text-[24px] font-semibold tracking-[-0.015em]">{t("signInTitle")}</h1>
            <p className="mt-1.5 text-[15px] leading-[22px] text-ink-2">{t("signInBody")}</p>
          </div>

          {config.isPending && <div className="skeleton h-11" />}
          {config.isError && <Notice icon="wifi_off">{t("serverUnreachable")}</Notice>}
          {nothing && <Notice icon="info">{t("signInUnavailable")}</Notice>}

          {config.data?.google_client_id && (
            <GoogleButton clientId={config.data.google_client_id} disabled={busy}
              onCredential={(token) => void run(() => signInWithGoogle(token))} onError={setError} />
          )}

          {error && (
            <p role="alert" className="flex gap-2 rounded-xl bg-error-soft px-3 py-2.5 text-sm leading-5 text-error-ink">
              <Icon name="error" size={18} /> {error}
            </p>
          )}
        </motion.section>
      </div>
    </div>
  );
}

function GoogleButton({ clientId, disabled, onCredential, onError }: {
  clientId: string; disabled: boolean; onCredential: (token: string) => void; onError: (m: string) => void;
}) {
  const t = useT();
  const lang = useUi((s) => s.lang);
  const el = useRef<HTMLDivElement>(null);
  const callback = useRef(onCredential);
  callback.current = onCredential;

  useEffect(() => {
    let cancelled = false;
    loadGis()
      .then((g) => {
        if (cancelled || !el.current) return;
        g.accounts.id.initialize({ client_id: clientId, callback: (r) => callback.current(r.credential) });
        g.accounts.id.renderButton(el.current, {
          theme: "outline", size: "large", shape: "pill", text: "continue_with", width: el.current.clientWidth || 320,
          locale: lang === "hi" ? "hi" : "en",
        });
      })
      .catch((e: Error) => onError(e.message));
    return () => {
      cancelled = true;
    };
  }, [clientId, lang, onError]);

  return (
    <div className={disabled ? "pointer-events-none opacity-60" : undefined}>
      <div ref={el} className="flex min-h-11 w-full justify-center" aria-label={t("signInGoogle")} />
    </div>
  );
}

function Notice({ icon, children }: { icon: string; children: string }) {
  return (
    <p className="flex gap-2 rounded-xl bg-surface-muted px-3 py-2.5 text-sm leading-5 text-ink-2">
      <Icon name={icon} size={18} /> {children}
    </p>
  );
}
