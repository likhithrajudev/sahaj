import { useEffect, useRef, useState } from "react";
import { api, auth, socketUrl } from "../api";
import { Answer, type Card, type Reply } from "../components/Answer";
import { useUser } from "../App";
import { Icon, LogoLockup } from "../brand";

type Item =
  | { id: string; kind: "me" | "sys" | "err"; text: string }
  | { id: string; kind: "draft"; trace: string; text: string }
  | { id: string; kind: "bot"; reply: Reply; card?: Card }
  | { id: string; kind: "agent"; name: string; text: string }
  | { id: string; kind: "consent"; purpose: string; title: string; text: string; version: string };

type CaseView = { id: string; reference: string; kind: string; status: string; priority: string; executives_online?: boolean };
type Lang = { code: string; name: string; speech_output: boolean };

const STAGES: Record<string, string> = {
  transcribing: "Listening…", speaking: "Speaking…", waiting_for_executive: "Waiting for a person from the team…",
};
const STEPS = ["Understanding your question", "Reading the clauses", "Checking every fact"];

// The server reports "thinking" then "checking"; retrieval happens in between, so the middle step follows a beat later.
function Steps({ stage }: { stage: string }) {
  const [reading, setReading] = useState(false);
  useEffect(() => {
    setReading(false);
    if (stage !== "thinking") return;
    const t = setTimeout(() => setReading(true), 1200);
    return () => clearTimeout(t);
  }, [stage]);
  const now = stage === "checking" ? 2 : reading ? 1 : 0;
  return (
    <div className="steps" role="status" aria-live="polite">
      {STEPS.map((label, i) => <span key={label} className={i < now ? "done" : i === now ? "now" : ""}>{label}</span>)}
    </div>
  );
}
let seq = 0;
const nid = () => String(++seq);

export function Chat() {
  const user = useUser();
  const [items, setItems] = useState<Item[]>([]);
  const [stage, setStage] = useState("");
  const [text, setText] = useState("");
  const [speakReplies, setSpeakReplies] = useState(true);
  const [langs, setLangs] = useState<Lang[]>([]);
  const [lang, setLang] = useState(user?.language || "en-IN");
  const [kase, setKase] = useState<CaseView | null>(null);
  const [toast, setToast] = useState<{ title: string; body: string } | null>(null);
  const [recording, setRecording] = useState(false);
  const ws = useRef<WebSocket | null>(null);
  const audio = useRef<Blob[]>([]);
  const card = useRef<Card | undefined>(undefined);
  const recorder = useRef<MediaRecorder | null>(null);
  const log = useRef<HTMLDivElement>(null);

  const add = (item: Item) => setItems((xs) => [...xs, item]);

  useEffect(() => {
    api<{ items: Lang[] }>("/languages").then((r) => setLangs(r.items)).catch(() => {});
  }, []);

  useEffect(() => {
    let closed = false;
    function open() {
      const socket = new WebSocket(socketUrl("/ws/voice", { resume: sessionStorage.getItem("sahaj.chat") ?? undefined }));
      socket.binaryType = "blob";
      socket.onmessage = ({ data }) => (data instanceof Blob ? audio.current.push(data) : onEvent(JSON.parse(data)));
      socket.onclose = async (e) => {
        if (closed) return;
        if (e.code === 4401 && (await auth.refresh())) return open();
        add({ id: nid(), kind: "sys", text: "Disconnected. Reconnecting…" });
        setTimeout(() => !closed && open(), 2000);
      };
      ws.current = socket;
    }
    open();
    return () => {
      closed = true;
      ws.current?.close();
    };
  }, []);

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight, behavior: "smooth" });
  }, [items, stage]);

  function send(message: object) {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(message));
  }

  function ask(t: string) {
    const clean = t.trim();
    if (!clean) return;
    send({ type: "text", text: clean, language: lang, speak: speakReplies });
    setText("");
  }

  function onEvent(m: any) {
    switch (m.type) {
      case "session":
        sessionStorage.setItem("sahaj.chat", m.id);
        setKase(m.case);
        if (m.resumed) add({ id: nid(), kind: "sys", text: "Picked up where you left off." });
        break;
      case "consent_required":
        add({ id: nid(), kind: "consent", purpose: m.purpose, title: m.title, text: m.text, version: m.version });
        break;
      case "consent":
        setItems((xs) => xs.filter((x) => !(x.kind === "consent" && x.purpose === m.purpose)));
        break;
      case "status":
        setStage(m.stage in STAGES || m.stage === "checking" || m.stage === "thinking" ? m.stage : "");
        break;
      case "user":
        add({ id: nid(), kind: "me", text: m.text });
        break;
      case "card":
        card.current = { kind: m.kind, card: m.card };
        break;
      case "assistant_delta":
        setStage("");
        setItems((xs) => {
          const last = xs[xs.length - 1];
          if (last?.kind === "draft" && last.trace === m.trace_id) return [...xs.slice(0, -1), { ...last, text: last.text + m.text }];
          return [...xs, { id: nid(), kind: "draft", trace: m.trace_id, text: m.text }];
        });
        break;
      case "assistant":
        setStage("");
        setItems((xs) => [...xs.filter((x) => !(x.kind === "draft" && x.trace === m.trace_id)), { id: nid(), kind: "bot", reply: m, card: card.current }]);
        card.current = undefined;
        break;
      case "done":
        setStage("");
        if (audio.current.length) new Audio(URL.createObjectURL(new Blob(audio.current, { type: "audio/mpeg" }))).play().catch(() => {});
        audio.current = [];
        break;
      case "handoff":
        setKase(m.case);
        add({ id: nid(), kind: "sys", text: `A person from the team will take it from here (ref ${m.reference}).` });
        break;
      case "agent_joined":
        setKase((k) => (k ? { ...k, status: "with_executive" } : k));
        add({ id: nid(), kind: "sys", text: `${m.agent.name} joined.` });
        break;
      case "agent_left":
        setKase((k) => (k ? { ...k, status: "waiting" } : k));
        break;
      case "agent_message":
        add({ id: nid(), kind: "agent", name: m.agent.name, text: m.text });
        break;
      case "video_kyc_scheduled":
        add({ id: nid(), kind: "sys", text: `Video KYC booked for ${new Date(m.scheduled_for).toLocaleString()}${m.meeting_url ? ` · ${m.meeting_url}` : ""}` });
        break;
      case "handoff_closed":
        setKase(null);
        add({ id: nid(), kind: "sys", text: m.message ? `${m.message} — Sahaj is answering again.` : "Sahaj is answering again." });
        break;
      case "inbox":
        setToast(m.item);
        setTimeout(() => setToast(null), 8000);
        break;
      case "usage_warning":
        add({ id: nid(), kind: "sys", text: `You've used ${m.percent_used}% of this month's allowance.` });
        break;
      case "budget_exceeded":
        add({ id: nid(), kind: "err", text: `This month's allowance is used up. It renews on ${new Date(m.resets_at).toLocaleDateString()}.` });
        break;
      case "error":
        setStage("");
        add({ id: nid(), kind: "err", text: m.message });
        break;
    }
  }

  async function holdToTalk(start: boolean) {
    if (start) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const chunks: Blob[] = [];
        const r = new MediaRecorder(stream);
        r.ondataavailable = (e) => chunks.push(e.data);
        r.onstop = async () => {
          stream.getTracks().forEach((t) => t.stop());
          ws.current?.send(await new Blob(chunks).arrayBuffer());
        };
        r.start();
        recorder.current = r;
        setRecording(true);
      } catch {
        add({ id: nid(), kind: "err", text: "Microphone not available." });
      }
    } else if (recorder.current) {
      recorder.current.stop();
      recorder.current = null;
      setRecording(false);
    }
  }

  async function changeLanguage(code: string) {
    setLang(code);
    const updated = await api<any>("/users/me", { method: "PATCH", json: { language: code } }).catch(() => null);
    if (updated) auth.setUser(updated);
  }

  return (
    <div className="chat">
      <div className="head" style={{ marginBottom: 0 }}>
        <div>
          <h1>Ask Sahaj</h1>
          <div className="mute">Policies, claims, loans and their small print — by voice or text.</div>
        </div>
        <div className="row">
          <select value={lang} onChange={(e) => changeLanguage(e.target.value)} aria-label="Language">
            {(langs.length ? langs : [{ code: lang, name: lang, speech_output: true }]).map((l) => (
              <option key={l.code} value={l.code}>{l.name}</option>
            ))}
          </select>
          <label className="row small"><input type="checkbox" checked={speakReplies} onChange={(e) => setSpeakReplies(e.target.checked)} /> Speak replies</label>
          <button className="btn sm" onClick={() => send({ type: "handoff" })}>Talk to a person</button>
          <button className="btn sm ghost" onClick={() => { sessionStorage.removeItem("sahaj.chat"); location.reload(); }}>New chat</button>
        </div>
      </div>

      <div className="log" ref={log}>
        {kase && (
          <div className={`banner ${kase.status === "with_executive" ? "info" : "warn"}`}>
            <b>{kase.status === "with_executive" ? "You're talking to a person from the team." : "Waiting for a person from the team."}</b>
            <span className="small">Case {kase.reference}{kase.executives_online === false ? " · nobody is on the desk right now; they'll reply here" : ""}</span>
            <span className="spacer" />
            <button className="btn sm" onClick={() => send({ type: "handoff_cancel" })}>Back to Sahaj</button>
          </div>
        )}
        {items.length === 0 && (
          <div className="card hero" style={{ alignSelf: "center", maxWidth: 620, width: "100%", textAlign: "center", padding: 32 }}>
            <LogoLockup size={30} inverse />
            <h2 style={{ fontSize: 22, margin: "18px 0 6px" }}>What would you like to understand today?</h2>
            <p className="mute" style={{ margin: "0 0 4px" }}>Ask about any policy or loan. Sahaj points out the hidden costs and cites every clause.</p>
            <div className="sugg on-hero" style={{ justifyContent: "center" }}>
              {["What are the hidden charges in my loan?", "What catches should I watch for in health insurance?",
                "What is the waiting period for pre-existing diseases?", "मेरे लोन में छुपे हुए शुल्क कौन से हैं?"].map((t) => (
                <button key={t} onClick={() => ask(t)}>{t}</button>
              ))}
            </div>
          </div>
        )}
        {items.map((it) => {
          switch (it.kind) {
            case "me": return <div key={it.id} className="msg me">{it.text}</div>;
            case "sys": return <div key={it.id} className="msg sys">{it.text}</div>;
            case "err": return <div key={it.id} className="msg err">{it.text}</div>;
            case "draft": return <div key={it.id} className="msg bot typing">{it.text}</div>;
            case "bot": return <Answer key={it.id} reply={it.reply} card={it.card} onAsk={ask} />;
            case "agent": return <div key={it.id} className="msg agent"><div className="small mute">{it.name}</div>{it.text}</div>;
            case "consent":
              return (
                <div key={it.id} className="msg ask">
                  <b>{it.title}</b>
                  <p className="small" style={{ margin: "6px 0 10px" }}>{it.text}</p>
                  <div className="row">
                    <button className="btn primary sm" onClick={() => send({ type: "consent", purpose: it.purpose, granted: true, version: it.version })}>I agree</button>
                    <button className="btn sm" onClick={() => send({ type: "consent", purpose: it.purpose, granted: false })}>No thanks</button>
                  </div>
                </div>
              );
          }
        })}
        {(stage === "thinking" || stage === "checking") && <Steps stage={stage} />}
        {STAGES[stage] && <div className="msg sys typing">{STAGES[stage]}</div>}
      </div>

      <form className="composer" onSubmit={(e) => { e.preventDefault(); ask(text); }}>
        <button type="button" className={`mic ${recording ? "rec" : ""}`} title="Hold to talk"
          onPointerDown={() => holdToTalk(true)} onPointerUp={() => holdToTalk(false)} onPointerLeave={() => recording && holdToTalk(false)}><Icon name="voice" /></button>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder={recording ? "Listening… release to send" : "Type a question, or hold the mic to talk"} maxLength={2000} />
        <button className="btn primary" disabled={!text.trim()}>Send</button>
      </form>

      {toast && (
        <div className="toast card">
          <div className="small mute">New offer</div>
          <b>{toast.title}</b>
          <div className="small">{toast.body}</div>
        </div>
      )}
    </div>
  );
}
