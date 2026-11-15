import { useEffect, useRef, useState } from "react";
import type { AuthConfig } from "@sahaj/contracts";
import { signIn } from "../api";

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
      <div className="card">
        <div className="logo" style={{ padding: 0, marginBottom: 12 }}><i />Sahaj</div>
        <h1>Insurance and loans, explained in your language</h1>
        <p className="mute">Every answer cites the clause it comes from. A person from the team is one tap away.</p>
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
    </div>
  );
}
