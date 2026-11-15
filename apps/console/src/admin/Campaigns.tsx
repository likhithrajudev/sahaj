import { useEffect, useState } from "react";
import { api } from "../api";

type Campaign = { id: string; title: string; body: string; status: string; recipients: number; skipped_cap: number; seen: number; clicked: number; has_image: boolean; created_at: string };

export function Campaigns() {
  const [list, setList] = useState<Campaign[]>([]);
  const [form, setForm] = useState({ title: "", body: "", cta_label: "", cta_url: "", platforms: "" });
  const [image, setImage] = useState<File | null>(null);
  const [preview, setPreview] = useState<Record<string, number>>({});
  const [error, setError] = useState("");
  const load = () => api<Campaign[]>("/admin/campaigns").then(setList).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const c = await api<Campaign>("/admin/campaigns", { method: "POST", json: {
        title: form.title, body: form.body, cta_label: form.cta_label || null, cta_url: form.cta_url || null,
        audience: form.platforms ? { platforms: form.platforms.split(",").map((s) => s.trim()) } : {},
      } });
      if (image) {
        const body = new FormData();
        body.append("file", image);
        await api(`/admin/campaigns/${c.id}/image`, { method: "POST", body });
      }
      setForm({ title: "", body: "", cta_label: "", cta_url: "", platforms: "" });
      setImage(null);
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function reach(id: string) {
    const d = await api<{ audience_size: number }>(`/admin/campaigns/${id}`);
    setPreview((p) => ({ ...p, [id]: d.audience_size }));
  }

  return (
    <>
      <div className="head"><div><h1>Campaigns</h1><div className="mute">Offers go only to people who opted in, at most a few a week.</div></div></div>
      <div className="grid g2" style={{ alignItems: "start" }}>
        <form className="card grid" onSubmit={create}>
          <h2>New campaign</h2>
          <label className="field">Title<input type="text" required maxLength={80} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
          <label className="field">Message<textarea required maxLength={500} rows={3} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} /></label>
          <div className="grid g2">
            <label className="field">Button label<input type="text" maxLength={30} value={form.cta_label} onChange={(e) => setForm({ ...form, cta_label: e.target.value })} /></label>
            <label className="field">Button link (https)<input type="url" pattern="https://.*" value={form.cta_url} onChange={(e) => setForm({ ...form, cta_url: e.target.value })} /></label>
          </div>
          <label className="field">Only these platforms (optional: web, android, ios)<input type="text" value={form.platforms} onChange={(e) => setForm({ ...form, platforms: e.target.value })} /></label>
          <label className="field">Image (PNG, JPEG or WebP, up to 5 MB)<input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => setImage(e.target.files?.[0] ?? null)} /></label>
          {error && <p className="error">{error}</p>}
          <button className="btn primary">Save as draft</button>
        </form>
        <div className="card">
          <h2>All campaigns</h2>
          {list.length === 0 ? <div className="empty">None yet.</div> : (
            <table>
              <thead><tr><th>Campaign</th><th>Reach</th><th /></tr></thead>
              <tbody>
                {list.map((c) => (
                  <tr key={c.id}>
                    <td><b>{c.title}</b> {c.has_image && <span className="pill">image</span>}<div className="small mute">{c.body}</div></td>
                    <td className="small">
                      {c.status === "sent" ? <>{c.recipients} sent · {c.seen} seen · {c.clicked} clicked{c.skipped_cap ? ` · ${c.skipped_cap} capped` : ""}</>
                        : <span className="pill">{c.status}</span>}
                      {preview[c.id] !== undefined && <div>{preview[c.id]} would receive it</div>}
                    </td>
                    <td className="row">
                      {c.status === "draft" && <>
                        <button className="btn sm" onClick={() => reach(c.id)}>Reach</button>
                        <button className="btn sm primary" onClick={async () => {
                          if (!confirm(`Send "${c.title}" now to everyone who opted in?`)) return;
                          await api(`/admin/campaigns/${c.id}/send`, { method: "POST" }).catch((e) => setError(e.message));
                          load();
                        }}>Send</button>
                        <button className="btn sm ghost" onClick={async () => { await api(`/admin/campaigns/${c.id}/cancel`, { method: "POST" }); load(); }}>Cancel</button>
                      </>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}
