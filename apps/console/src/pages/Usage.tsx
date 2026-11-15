import { useEffect, useState } from "react";
import type { UsageSummary } from "@sahaj/contracts";
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { COLORS } from "../admin/Dashboard";

export function Usage() {
  const [u, setU] = useState<UsageSummary | null>(null);
  useEffect(() => { api<UsageSummary>("/users/me/usage").then(setU).catch(() => {}); }, []);
  if (!u) return <p className="mute">Loading…</p>;
  const used = Math.min(100, u.percent_used ?? 0);
  const byKind = Object.entries(u.by_kind).map(([name, value]) => ({ name, value: Number(value) }));
  const byPurpose = Object.entries(u.by_purpose).map(([name, value]) => ({ name, value: Number(value) }));
  return (
    <>
      <div className="head"><div><h1>Usage</h1><div className="mute">This month, until {new Date(u.period.resets_at).toLocaleDateString()}. Estimated from provider prices.</div></div></div>
      <div className="grid g4" style={{ marginBottom: 16 }}>
        <Kpi v={`$${u.spent_usd.toFixed(4)}`} l="Spent" />
        <Kpi v={`$${u.remaining_usd.toFixed(2)}`} l={`Left of $${u.budget_usd}`} />
        <Kpi v={String(u.model_calls)} l="AI answers and checks" />
        <Kpi v={u.tokens.input ? `${Math.round((100 * u.tokens.cached_input) / u.tokens.input)}%` : "–"} l="Served from cache" />
      </div>
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="row"><b>Monthly allowance</b><span className="spacer" /><span className="mute">{used.toFixed(1)}%</span></div>
        <div style={{ height: 10, background: "var(--surface-2)", borderRadius: 99, marginTop: 8, overflow: "hidden" }}>
          <div style={{ width: `${used}%`, height: "100%", background: used > 80 ? "var(--warn)" : "var(--primary)" }} />
        </div>
      </div>
      <div className="grid g2">
        <div className="card"><h2>By kind</h2>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart><Pie data={byKind} dataKey="value" nameKey="name" innerRadius={55} outerRadius={85} paddingAngle={2}>
              {byKind.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}</Pie>
              <Tooltip formatter={(v: number) => `$${v.toFixed(5)}`} /></PieChart>
          </ResponsiveContainer>
        </div>
        <div className="card"><h2>By purpose</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={byPurpose}><XAxis dataKey="name" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number) => `$${v.toFixed(5)}`} /><Bar dataKey="value" fill="var(--primary)" radius={[6, 6, 0, 0]} /></BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </>
  );
}

export function Kpi({ v, l }: { v: string; l: string }) {
  return <div className="card kpi"><div className="v">{v}</div><div className="l">{l}</div></div>;
}
