import { useEffect, useState } from "react";
import type { ConsentItem } from "@sahaj/contracts";
import { api, auth, download } from "../api";

type Memory = {
  consent: boolean;
  facts: { id: number; key: string; content: string }[];
  episodes: { id: string; ended_at: string; outcome: string; summary: string | null; intents: Record<string, number> }[];
};

export function Privacy() {
  const [consents, setConsents] = useState<ConsentItem[]>([]);
  const [memory, setMemory] = useState<Memory | null>(null);
  const [error, setError] = useState("");

  const load = () => {
    api<{ items: ConsentItem[] }>("/consents").then((r) => setConsents(r.items)).catch((e) => setError(e.message));
    api<Memory>("/users/me/memory").then(setMemory).catch(() => {});
  };
  useEffect(load, []);

  async function decide(c: ConsentItem, granted: boolean) {
    if (!granted && !confirm(`${c.withdrawal}\n\nWithdraw "${c.title}"?`)) return;
    await api(`/consents/${c.purpose}`, { method: "PUT", json: granted ? { granted, version: c.version } : { granted } }).catch((e) => setError(e.message));
    load();
  }

  return (
    <>
      <div className="head">
        <div>
          <h1>Privacy & memory</h1>
          <div className="mute">What you've agreed to, what Sahaj remembers, and your data.</div>
        </div>
        <div className="row">
          <button className="btn" onClick={async () => download(await api<Blob>("/users/me/export"), "sahaj-my-data.json")}>Download my data</button>
          <button className="btn danger" onClick={async () => {
            if (!confirm("Delete your account, memory and stored files? This cannot be undone.")) return;
            await api("/users/me", { method: "DELETE" });
            auth.signOut();
          }}>Delete account</button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="grid g2">
        {consents.filter((c) => c.purpose !== "video_kyc").map((c) => (
          <div className="card" key={c.purpose}>
            <div className="row">
              <b>{c.title}</b>
              <span className="spacer" />
              {c.required && <span className="pill info">Required</span>}
              <span className={`pill ${c.granted ? "ok" : c.action === "renew" ? "warn" : ""}`}>{c.granted ? "On" : c.action === "renew" ? "Renew" : "Off"}</span>
            </div>
            <p className="small mute">{c.text}</p>
            {c.granted_at && <div className="small mute">Since {new Date(c.granted_at * 1000).toLocaleDateString()} · until {new Date((c.expires_at ?? 0) * 1000).toLocaleDateString()}</div>}
            <div className="row" style={{ marginTop: 10 }}>
              {c.granted ? <button className="btn sm danger" onClick={() => decide(c, false)}>Withdraw</button>
                : <button className="btn sm primary" onClick={() => decide(c, true)}>{c.action === "renew" ? "Renew" : "Allow"}</button>}
              {c.requires && <span className="small mute">Needs “{consents.find((x) => x.purpose === c.requires)?.title}”</span>}
            </div>
          </div>
        ))}
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <div className="row" style={{ marginBottom: 8 }}>
          <h2 style={{ margin: 0 }}>What Sahaj remembers</h2>
          <span className="spacer" />
          <button className="btn sm danger" onClick={async () => { await api("/users/me/memory", { method: "DELETE" }); load(); }}>Erase all</button>
        </div>
        {!memory?.consent && <p className="small mute">Memory is off. Turn on “Remember me between conversations” above.</p>}
        {memory && memory.facts.length + memory.episodes.length === 0 ? <div className="empty">Nothing remembered.</div> : (
          <table>
            <tbody>
              {memory?.facts.map((f) => (
                <tr key={`f${f.id}`}><td className="mute">{f.key.replace(/_/g, " ")}</td><td>{f.content}</td>
                  <td><button className="btn sm danger" onClick={async () => { await api(`/users/me/memory/${f.id}`, { method: "DELETE" }); load(); }}>Forget</button></td></tr>
              ))}
              {memory?.episodes.map((e) => (
                <tr key={e.id}><td className="mute">{new Date(e.ended_at).toLocaleDateString()}</td>
                  <td>{e.summary || Object.keys(e.intents).join(", ")} <span className="pill">{e.outcome.replace(/_/g, " ")}</span></td>
                  <td><button className="btn sm danger" onClick={async () => { await api(`/users/me/memory/episodes/${e.id}`, { method: "DELETE" }); load(); }}>Forget</button></td></tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
