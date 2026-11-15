import { useEffect, useRef, useState } from "react";
import type { AuthConfig } from "@sahaj/contracts";
import { signIn } from "../api";
import { Icon, LogoLockup } from "../brand";

declare global {
  interface Window {
    google?: { accounts: { id: { initialize(o: object): void; renderButton(el: HTMLElement, o: object): void } } };
  }
}

export function SignIn() {
  const [cfg, setCfg] = useState<AuthConfig | null>(null);
  const [email, setEmail] = useState("tester@example.com");
  const [error, setError] = useState("");
  const button = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch("/auth/config").then((r) => r.json()).then(setCfg).catch(() => setError("The API is not reachable."));
  }, []);

  useEffect(() => {
    if (!cfg?.google_client_id || !button.current) return;
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => {
      window.google!.accounts.id.initialize({
        client_id: cfg.google_client_id,
        callback: ({ credential }: { credential: string }) =>
          signIn("/auth/google", { id_token: credential, platform: "web" }).catch((e) => setError(e.message)),
      });
      window.google!.accounts.id.renderButton(button.current!, { theme: "outline", size: "large", width: 320 });
    };
    document.head.append(script);
    return () => script.remove();
  }, [cfg]);

  return (
    <div className="signin">
      <section className="hero-side">
        <LogoLockup size={34} inverse />
        <div>
          <h1>Insurance and loans, explained in your language</h1>
          <p>Ask in Hindi, Tamil, English or any of 22 languages. Sahaj reads the fine print so the hidden costs are never hidden.</p>
        </div>
        <ul className="facts">
          <li><Icon name="doc" />Every answer cites the clause it comes from.</li>
          <li><Icon name="shield" />Nothing personal is used without your permission.</li>
          <li><Icon name="headset" />A person from the team is one tap away.</li>
        </ul>
      </section>
      <section className="form-side">
      <div className="card">
        <h2 style={{ fontSize: 22 }}>Sign in</h2>
        <p className="mute" style={{ marginTop: 0 }}>Use your Google account to continue.</p>
        <div style={{ margin: "20px 0" }} ref={button} />
        {cfg?.dev_login && (
          <form className="grid" onSubmit={(e) => { e.preventDefault(); signIn("/auth/dev", { email }).catch((err) => setError(err.message)); }}>
            <label className="field">Development sign-in (this machine only)
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </label>
            <button className="btn primary">Continue</button>
          </form>
        )}
        {cfg && !cfg.google_client_id && !cfg.dev_login && (
          <p className="mute small">No sign-in is configured on the server: set GOOGLE_CLIENT_IDS (or DEV_LOGIN for local development).</p>
        )}
        {error && <p className="error">{error}</p>}
      </div>
      </section>
    </div>
  );
}
