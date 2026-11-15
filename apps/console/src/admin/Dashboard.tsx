import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { User } from "@sahaj/contracts";
import { api } from "../api";
import { Kpi } from "../pages/Usage";

// brand-first categorical palette from the design tokens
export const COLORS = ["#004299", "#00b8f5", "#0f766e", "#e0a100", "#012a72", "#c0262d", "#7c8da6"];

type Spender = { email: string; username: string; spent_usd: number; budget_usd: number };
type Desk = { items: { priority: string; kind: string; status: string; overdue: boolean }[]; stats: { waiting: number; in_progress: number; overdue: number; urgent_waiting: number; avg_wait_seconds: number | null } };
type Campaign = { id: string; title: string; status: string; recipients: number; seen: number; clicked: number };

const count = <T,>(xs: T[], key: (x: T) => string) =>
  Object.entries(xs.reduce<Record<string, number>>((m, x) => ({ ...m, [key(x)]: (m[key(x)] ?? 0) + 1 }), {})).map(([name, value]) => ({ name, value }));

export function Dashboard() {
  const [users, setUsers] = useState<User[]>([]);
  const [spend, setSpend] = useState<{ items: Spender[]; default_budget_usd: number } | null>(null);
  const [desk, setDesk] = useState<Desk | null>(null);
  const [feedback, setFeedback] = useState<{ counts: { up: number; down: number } } | null>(null);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);

  useEffect(() => {
    api<User[]>("/admin/users?limit=200").then(setUsers).catch(() => {});
    api<typeof spend>("/admin/usage?limit=10").then(setSpend).catch(() => {});
    api<Desk>("/desk/queue?view=all").then(setDesk).catch(() => {});
    api<typeof feedback>("/admin/feedback?limit=1").then(setFeedback).catch(() => {});
    api<Campaign[]>("/admin/campaigns").then(setCampaigns).catch(() => {});
  }, []);

  const totalSpend = spend?.items.reduce((s, x) => s + x.spent_usd, 0) ?? 0;
  const fb = feedback?.counts ?? { up: 0, down: 0 };
  const satisfaction = fb.up + fb.down ? Math.round((100 * fb.up) / (fb.up + fb.down)) : null;
  const sent = campaigns.filter((c) => c.status === "sent");

  return (
    <>
      <div className="head"><div><h1>Dashboard</h1><div className="mute">Everything in your organisation at a glance.</div></div></div>
      <div className="grid g4" style={{ marginBottom: 16 }}>
        <Kpi v={String(users.length)} l="People" />
        <Kpi v={`$${totalSpend.toFixed(3)}`} l="AI spend this month (top 10)" />
        <Kpi v={desk ? String(desk.stats.waiting) : "–"} l={`Waiting for the desk${desk?.stats.overdue ? ` · ${desk.stats.overdue} overdue` : ""}`} />
        <Kpi v={satisfaction === null ? "–" : `${satisfaction}%`} l={`Helpful answers (${fb.up + fb.down} ratings)`} />
      </div>
      <div className="grid g2" style={{ marginBottom: 16 }}>
        <div className="card"><h2>Top spenders this month</h2>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={spend?.items ?? []} layout="vertical" margin={{ left: 30 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" /><XAxis type="number" tick={{ fontSize: 11 }} />
              <YAxis type="category" dataKey="username" tick={{ fontSize: 11 }} width={90} />
              <Tooltip formatter={(v: number) => `$${v.toFixed(5)}`} />
              <Bar dataKey="spent_usd" name="Spent" fill={COLORS[0]} radius={[0, 6, 6, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="card"><h2>Desk queue</h2>
          {desk && desk.items.length ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={count(desk.items, (c) => c.priority)}>
                <XAxis dataKey="name" tick={{ fontSize: 11 }} /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} /><Tooltip />
                <Bar dataKey="value" name="Cases" radius={[6, 6, 0, 0]}>
                  {count(desk.items, (c) => c.priority).map((d, i) => <Cell key={i} fill={d.name === "urgent" ? COLORS[5] : d.name === "high" ? COLORS[3] : COLORS[0]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : <div className="empty">No open cases.{desk?.stats.avg_wait_seconds ? ` Average wait ${Math.round(desk.stats.avg_wait_seconds / 60)} min.` : ""}</div>}
        </div>
      </div>
      <div className="grid g3">
        <div className="card"><h2>People by platform</h2>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart><Pie data={count(users, (u) => u.platform)} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80} paddingAngle={2}>
              {count(users, (u) => u.platform).map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}</Pie><Legend /><Tooltip /></PieChart>
          </ResponsiveContainer>
        </div>
        <div className="card"><h2>People by language</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={count(users, (u) => u.language)}><XAxis dataKey="name" tick={{ fontSize: 11 }} /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} /><Tooltip />
              <Bar dataKey="value" name="People" fill={COLORS[1]} radius={[6, 6, 0, 0]} /></BarChart>
          </ResponsiveContainer>
        </div>
        <div className="card"><h2>Campaign results</h2>
          {sent.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={sent.slice(0, 6)}><XAxis dataKey="title" tick={{ fontSize: 10 }} /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} /><Tooltip /><Legend />
                <Bar dataKey="recipients" fill={COLORS[0]} /><Bar dataKey="seen" fill={COLORS[2]} /><Bar dataKey="clicked" fill={COLORS[3]} /></BarChart>
            </ResponsiveContainer>
          ) : <div className="empty">No campaigns sent yet.</div>}
        </div>
      </div>
    </>
  );
}
