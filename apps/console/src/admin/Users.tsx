import { useEffect, useState } from "react";
import type { User } from "@sahaj/contracts";
import { api } from "../api";
import { useUser } from "../App";

export function Users() {
  const me = useUser();
  const [users, setUsers] = useState<User[]>([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState("");
  const load = () => api<User[]>("/admin/users?limit=200").then(setUsers).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function setRole(u: User, role: string) {
    await api(`/admin/users/${u.id}/role`, { method: "PATCH", json: { role } }).catch((e) => setError(e.message));
    load();
  }
  async function setBudget(u: User) {
    const v = prompt(`Monthly AI allowance for ${u.email} in USD (empty for the default):`);
    if (v === null) return;
    await api(`/admin/users/${u.id}/budget`, { method: "PATCH", json: { budget_usd: v.trim() ? Number(v) : null } }).catch((e) => setError(e.message));
  }

  const shown = users.filter((u) => `${u.email} ${u.name ?? ""} ${u.username ?? ""}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <div className="head">
        <div><h1>People</h1><div className="mute">{users.length} in this organisation</div></div>
        <input type="text" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {error && <p className="error">{error}</p>}
      <div className="card">
        <table>
          <thead><tr><th>Person</th><th>Language</th><th>Platform</th><th>Role</th><th /></tr></thead>
          <tbody>
            {shown.map((u) => (
              <tr key={u.id}>
                <td><b>{u.name || u.username}</b><div className="small mute">{u.email}</div></td>
                <td>{u.language}</td>
                <td>{u.platform}</td>
                <td>
                  <select value={u.role} disabled={u.id === me?.id} onChange={(e) => setRole(u, e.target.value)}>
                    <option value="user">user</option><option value="executive">executive</option><option value="admin">admin</option>
                  </select>
                </td>
                <td><button className="btn sm" onClick={() => setBudget(u)}>Allowance</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
