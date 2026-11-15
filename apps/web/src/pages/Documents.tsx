import { useEffect, useRef, useState } from "react";
import { api, download } from "../api";

type FileRow = { id: string; filename: string; content_type: string; size_bytes: number; created_at: string; index_status: string; indexed_chunks: number; category: string };
type Listing = { consent: boolean; analysis_consent: boolean; consent_text: Consent; analysis_consent_text: Consent; items: FileRow[]; limits: { max_bytes: number } };
type Consent = { purpose: string; version: string; text: string; title?: string };

const STATUS: Record<string, [string, string]> = {
  ready: ["ok", "Readable"], indexing: ["info", "Reading…"], none: ["", "Stored"], empty: ["warn", "No text found"],
  unsupported: ["", "Stored only"], failed: ["bad", "Couldn't read"], over_budget: ["warn", "Allowance used up"],
};

export function Documents() {
  const [data, setData] = useState<Listing | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = () => api<Listing>("/files").then(setData).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!data?.items.some((f) => f.index_status === "indexing")) return;
    const t = setTimeout(load, 1500);
    return () => clearTimeout(t);
  }, [data]);

  async function consent(c: Consent, granted: boolean) {
    await api(`/consents/${c.purpose}`, { method: "PUT", json: granted ? { granted, version: c.version } : { granted } }).catch((e) => setError(e.message));
    load();
  }

  async function upload(file: File) {
    setBusy(true);
    setError("");
    const body = new FormData();
    body.append("file", file);
    await api("/files", { method: "POST", body }).catch((e) => setError(e.message));
    setBusy(false);
    load();
  }

  if (!data) return <p className="mute">{error || "Loading…"}</p>;
  return (
    <>
      <div className="head">
        <div>
          <h1>Your documents</h1>
          <div className="mute">Policies, loan offers, bills and prescriptions. Sahaj can answer questions about them, with the page cited.</div>
        </div>
      </div>
      <div className="grid g2" style={{ marginBottom: 16 }}>
        {[data.consent_text, data.analysis_consent_text].map((c, i) => {
          const on = i === 0 ? data.consent : data.analysis_consent;
          return (
            <div className="card" key={c.purpose}>
              <div className="row"><b>{i === 0 ? "Store my documents" : "Let Sahaj read them"}</b><span className="spacer" /><span className={`pill ${on ? "ok" : ""}`}>{on ? "On" : "Off"}</span></div>
              <p className="small mute">{c.text}</p>
              <button className={`btn sm ${on ? "danger" : "primary"}`} disabled={i === 1 && !data.consent} onClick={() => consent(c, !on)}>{on ? "Turn off" : "Allow"}</button>
            </div>
          );
        })}
      </div>
      <div className="card">
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>Files</h2>
          <span className="spacer" />
          <input ref={input} type="file" hidden accept="application/pdf,image/*,.docx,.xlsx,.pptx,.txt,audio/*" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          <button className="btn primary" disabled={!data.consent || busy} onClick={() => input.current?.click()}>{busy ? "Uploading…" : "Upload"}</button>
        </div>
        {error && <p className="error">{error}</p>}
        {data.items.length === 0 ? <div className="empty">No documents yet.</div> : (
          <table>
            <thead><tr><th>Name</th><th>Kind</th><th>Size</th><th>Status</th><th /></tr></thead>
            <tbody>
              {data.items.map((f) => {
                const [cls, label] = STATUS[f.index_status] ?? ["", f.index_status];
                return (
                  <tr key={f.id}>
                    <td>{f.filename}<div className="small mute">{new Date(f.created_at).toLocaleString()}</div></td>
                    <td>{f.category}</td>
                    <td>{(f.size_bytes / 1024).toFixed(0)} KB</td>
                    <td><span className={`pill ${cls}`}>{label}{f.index_status === "ready" ? ` · ${f.indexed_chunks}` : ""}</span></td>
                    <td className="row">
                      <button className="btn sm" onClick={async () => download(await api<Blob>(`/files/${f.id}`), f.filename)}>Download</button>
                      <button className="btn sm danger" onClick={async () => { await api(`/files/${f.id}`, { method: "DELETE" }); load(); }}>Delete</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
