import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { LogoLockup } from "@/components/brand/logo";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { getAuthConfig, signInDev, signInWithGoogle } from "@/lib/auth";
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

  const nothing = config.data && !config.data.google_client_id && !config.data.dev_login;

  return (
    <div className="pt-safe pb-safe flex h-full flex-col overflow-y-auto bg-bg">
      <div className="px-gutter mx-auto flex w-full max-w-[440px] flex-1 flex-col justify-center gap-8 py-10">
        <div className="flex flex-col items-center gap-3 text-center">
          <LogoLockup size={44} />
          <p className="text-[17px] text-ink-2">{t("tagline")}</p>
        </div>

        <section className="flex flex-col gap-5 rounded-[20px] border border-line bg-surface p-6">
          <div>
            <h1 className="text-[22px] font-semibold">{t("signInTitle")}</h1>
            <p className="mt-1.5 text-[15px] leading-[22px] text-ink-2">{t("signInBody")}</p>
          </div>

          {config.isPending && <div className="skeleton h-11" />}
          {config.isError && <Notice icon="wifi_off">{t("serverUnreachable")}</Notice>}
          {nothing && <Notice icon="info">{t("signInUnavailable")}</Notice>}

          {config.data?.google_client_id && (
            <GoogleButton clientId={config.data.google_client_id} disabled={busy}
              onCredential={(token) => void run(() => signInWithGoogle(token))} onError={setError} />
          )}

          {config.data?.dev_login && <DevLogin busy={busy} onSubmit={(email, name) => void run(() => signInDev(email, name))} />}

          {error && (
            <p role="alert" className="flex gap-2 rounded-xl bg-error-soft px-3 py-2.5 text-sm leading-5 text-error-ink">
              <Icon name="error" size={18} /> {error}
            </p>
          )}
        </section>

        <p className="flex items-center justify-center gap-2 text-center text-sm text-ink-3">
          <Badge tone="sample" icon="science">{t("sample")}</Badge> {t("sampleShort")}
        </p>
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

function DevLogin({ busy, onSubmit }: { busy: boolean; onSubmit: (email: string, name: string) => void }) {
  const t = useT();
  const [email, setEmail] = useState("demo@sahaj.local");
  const [name, setName] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit(email.trim(), name.trim());
  };
  return (
    <form onSubmit={submit} className="flex flex-col gap-3 rounded-2xl border border-dashed border-line-2 p-4">
      <div className="flex items-center gap-2">
        <Icon name="science" size={18} className="text-sample-ink" />
        <span className="text-[15px] font-semibold">{t("devLoginTitle")}</span>
      </div>
      <p className="text-[13px] leading-[18px] text-ink-3">{t("devLoginNote")}</p>
      <label className="flex flex-col gap-1 text-sm font-medium text-ink-2">
        {t("email")}
        <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email"
          className="h-12 rounded-xl border border-line-2 bg-surface px-3.5 text-[17px] text-ink outline-none focus:border-primary" />
      </label>
      <label className="flex flex-col gap-1 text-sm font-medium text-ink-2">
        {t("name")}
        <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name"
          className="h-12 rounded-xl border border-line-2 bg-surface px-3.5 text-[17px] text-ink outline-none focus:border-primary" />
      </label>
      <Button type="submit" disabled={busy}>{busy ? t("signingIn") : t("signInAction")}</Button>
    </form>
  );
}

function Notice({ icon, children }: { icon: string; children: string }) {
  return (
    <p className="flex gap-2 rounded-xl bg-surface-2 px-3 py-2.5 text-sm leading-5 text-ink-2">
      <Icon name={icon} size={18} /> {children}
    </p>
  );
}
