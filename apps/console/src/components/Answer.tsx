import { useState } from "react";
import { api } from "../api";
import { Icon } from "../brand";

export type Reply = {
  trace_id: string;
  agent: string;
  text: string;
  structured: { kind: string; summary: string; points: { text: string; sources: string[] }[]; sources: { id: string; text: string }[]; notes: string[] };
  verification: { level: "verified" | "engine" | "checked" | "blocked"; from_cache: boolean };
  suggestions: string[];
};

const AGENT: Record<string, string> = { loan: "Loan expert", insurance: "Insurance expert", advisory: "Advisor", calculator: "Calculator" };

const BADGE = {
  verified: ["ok", "Checked against your documents"],
  engine: ["info", "Worked out by Sahaj's calculator"],
  checked: ["warn", "Screened, nothing to cite"],
  blocked: ["bad", "Couldn't confirm, safe reply shown"],
} as const;

export function Answer({ reply, card, onAsk }: { reply: Reply; card?: Card; onAsk: (t: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const [rated, setRated] = useState<"up" | "down" | null>(null);
  const s = reply.structured;
  const source = Object.fromEntries(s.sources.map((x) => [x.id, x.text]));
  const [cls, label] = BADGE[reply.verification.level];
  const order = s.sources.map((x) => x.id);
  const prose = s.points.length <= 3;
  const Marks = ({ ids }: { ids: string[] }) => (
    <>{ids.map((id) => (
      <button key={id} className={`cite ${open === id ? "on" : ""}`} onClick={() => setOpen(open === id ? null : id)}
        aria-label={`Source ${order.indexOf(id) + 1}`}>{order.indexOf(id) + 1}</button>
    ))}</>
  );

  async function rate(rating: "up" | "down") {
    const comment = rating === "down" ? prompt("What was wrong? (optional)") : null;
    await api("/feedback", { method: "POST", json: { trace_id: reply.trace_id, rating, comment: comment || null } }).catch(() => {});
    setRated(rating);
  }

  return (
    <div className="msg bot">
      <span className={`pill ${cls}`}>{label}{reply.verification.from_cache ? " · instant" : ""}</span>
      {prose ? (
        <p className="prose">{s.points.map((p, i) => <span key={i}>{p.text}<Marks ids={p.sources} />{" "}</span>)}</p>
      ) : (
        <>
          <p className="prose">{s.points[0].text}<Marks ids={s.points[0].sources} /></p>
          <ul className="points">
            {s.points.slice(1).map((p, i) => <li key={i}>{p.text}<Marks ids={p.sources} /></li>)}
          </ul>
        </>
      )}
      {open && source[open] && (
        <div className="source"><b>Source {order.indexOf(open) + 1}</b>{"\n"}{source[open]}</div>
      )}
      {s.notes.map((n, i) => <div key={i} className="small mute">{n}</div>)}
      {card && <CardView card={card} />}
      <div className="row small mute" style={{ marginTop: 6 }}>
        <span className="rate">
          <button className={rated === "up" ? "on" : ""} onClick={() => rate("up")} title="Helpful" aria-label="Helpful"><Icon name="up" size={16} /></button>
          <button className={rated === "down" ? "on" : ""} onClick={() => rate("down")} title="Not helpful" aria-label="Not helpful"><Icon name="down" size={16} /></button>
        </span>
        {AGENT[reply.agent] && <span>{AGENT[reply.agent]}</span>}
      </div>
      {reply.suggestions.length > 0 && (
        <div className="sugg">{reply.suggestions.map((t) => <button key={t} onClick={() => onAsk(t)}>{t}</button>)}</div>
      )}
    </div>
  );
}

export type Card = { kind: string; card: Record<string, any> };

function CardView({ card }: { card: Card }) {
  const c = card.card;
  if (card.kind === "fine_print" && Array.isArray(c.topics)) {
    return (
      <details style={{ marginTop: 8 }}>
        <summary className="small mute">What was checked ({c.topics.length} topics)</summary>
        <ul className="small">
          {c.topics.map((t: { topic: string; sources: string[] }) => (
            <li key={t.topic}>{t.sources.length ? "✓" : "–"} {t.topic}</li>
          ))}
        </ul>
      </details>
    );
  }
  if (Array.isArray(c.plans) && c.plans[0]?.rows) {
    return (
      <table style={{ marginTop: 8 }}>
        <thead><tr><th />{c.plans.map((p: any) => <th key={p.name}>{p.name}</th>)}</tr></thead>
        <tbody>
          {c.plans[0].rows.map((_: unknown, i: number) => (
            <tr key={i}><td className="mute">{c.plans[0].rows[i][0]}</td>{c.plans.map((p: any) => <td key={p.name}>{p.rows[i]?.[1]}</td>)}</tr>
          ))}
        </tbody>
      </table>
    );
  }
  return (
    <details style={{ marginTop: 8 }}>
      <summary className="small mute">Details</summary>
      <pre className="small" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(c, null, 2)}</pre>
    </details>
  );
}
