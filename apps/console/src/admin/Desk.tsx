import { useEffect, useRef, useState } from "react";
import { api, socketUrl } from "../api";
import { useUser } from "../App";

type QueueItem = { id: string; reference: string; kind: string; reason: string; priority: string; status: string; created_at: string; sla_due_at: string; overdue: boolean; customer: { name: string | null; username: string }; assigned_to: string | null; messages: number };
type Detail = {
  case: QueueItem & { note: string | null; trace_id: string | null; channel: string | null };
  conversation_before: { role: string; content: string }[];
  messages: { id: number; at: string; sender: string; text: string }[];
  customer: { name: string | null; email: string; language: string; online: boolean; consents: string[] } | null;
};

const PRIORITY: Record<string, string> = { urgent: "bad", high: "warn", normal: "" };

export function Desk() {
  const me = useUser();
  const [view, setView] = useState("open");
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [open, setOpen] = useState<Detail | null>(null);
  const [reply, setReply] = useState("");
  const [error, setError] = useState("");
  const current = useRef<string | null>(null);

  const loadQueue = () => api<{ items: QueueItem[] }>(`/desk/queue?view=${view}`).then((r) => setQueue(r.items)).catch((e) => setError(e.message));
  const loadCase = (id: string) => api<Detail>(`/desk/cases/${id}`).then((d) => { current.current = id; setOpen(d); });

  useEffect(() => { loadQueue(); }, [view]);
  useEffect(() => {
    const ws = new WebSocket(socketUrl("/ws/desk"));
    ws.onmessage = ({ data }) => {
      const m = JSON.parse(data);
      if (m.type !== "queue") loadQueue();
      if (current.current && (m.case_id === current.current || m.case?.id === current.current)) loadCase(current.current);
    };
    return () => ws.close();
  }, [view]);

  async function act(path: string, body?: unknown) {
    setError("");
    try {
      await api(`/desk/cases/${open!.case.id}/${path}`, { method: "POST", json: body ?? {} });
      await loadCase(open!.case.id);
      loadQueue();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const mine = open?.case.assigned_to === me?.id && open?.case.status === "assigned";
  return (
    <>
      <div className="head">
        <div><h1>Desk</h1><div className="mute">Conversations that need a person. Live.</div></div>
        <div className="row">{["open", "mine", "overdue", "all"].map((v) => (
          <button key={v} className={`btn sm ${view === v ? "primary" : ""}`} onClick={() => setView(v)}>{v}</button>
        ))}</div>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="grid" style={{ gridTemplateColumns: "minmax(260px, 340px) 1fr", alignItems: "start" }}>
        <div className="card" style={{ padding: 8 }}>
          {queue.length === 0 ? <div className="empty">Nothing here.</div> : queue.map((c) => (
            <button key={c.id} onClick={() => loadCase(c.id)} className="btn ghost"
              style={{ width: "100%", textAlign: "left", border: open?.case.id === c.id ? "1px solid var(--brand)" : "1px solid transparent", marginBottom: 4 }}>
              <div className="row"><b>{c.customer.name || c.customer.username}</b><span className="spacer" /><span className={`pill ${PRIORITY[c.priority]}`}>{c.priority}</span></div>
              <div className="small mute">{c.reason.replace(/_/g, " ")} · {c.kind}{c.overdue ? " · overdue" : ""}</div>
            </button>
          ))}
        </div>
        {!open ? <div className="card empty">Pick a case.</div> : (
          <div className="card grid">
            <div className="row">
              <h2 style={{ margin: 0 }}>{open.customer?.name || open.case.customer?.username} <span className="mute small">ref {open.case.reference}</span></h2>
              <span className="spacer" />
              <span className={`pill ${open.customer?.online ? "ok" : ""}`}>{open.customer?.online ? "online" : "offline"}</span>
              <span className="pill">{open.customer?.language}</span>
            </div>
            <div className="small mute">{open.case.reason.replace(/_/g, " ")} · {open.case.channel} · consents: {open.customer?.consents.join(", ") || "none"}</div>
            {open.case.note && <div className="banner warn">{open.case.note}</div>}
            <details open>
              <summary className="small mute">Conversation before the handoff</summary>
              {open.conversation_before.map((m, i) => <div key={i} className="small"><b>{m.role}:</b> {m.content}</div>)}
            </details>
            <div className="grid" style={{ gap: 6 }}>
              {open.messages.map((m) => (
                <div key={m.id} className={`msg ${m.sender === "customer" ? "bot" : m.sender === "executive" ? "me" : "sys"}`}>{m.text}</div>
              ))}
            </div>
            {open.case.status === "open" && <button className="btn primary" onClick={() => act("claim")}>Take this case</button>}
            {mine && (
              <>
                <form className="composer" onSubmit={(e) => { e.preventDefault(); if (reply.trim()) act("messages", { text: reply }).then(() => setReply("")); }}>
                  <input value={reply} onChange={(e) => setReply(e.target.value)} placeholder="Write to the customer" />
                  <button className="btn primary">Send</button>
                </form>
                <div className="row">
                  {open.case.kind === "video_kyc" && <button className="btn sm" onClick={() => {
                    const when = prompt("Video KYC time (e.g. 2026-11-20T15:00+05:30)");
                    const url = when && prompt("Meeting link (https, optional)");
                    if (when) act("video-kyc", { scheduled_for: when, meeting_url: url || null });
                  }}>Book video KYC</button>}
                  <button className="btn sm" onClick={() => act("release")}>Put back in queue</button>
                  <span className="spacer" />
                  <button className="btn sm primary" onClick={() => {
                    const resolution = prompt("What was done? (for the record)");
                    if (resolution) act("resolve", { outcome: "resolved", resolution, message: "Thanks for your patience. Sahaj will take it from here." });
                  }}>Resolve</button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </>
  );
}
