import { useEffect, useState } from "react";
import { api } from "../api";

type Offer = { id: string; title: string; body: string; cta_label: string | null; has_image: boolean; delivered_at: string; seen_at: string | null };

export function Inbox() {
  const [items, setItems] = useState<Offer[]>([]);
  const [consent, setConsent] = useState(false);
  const [images, setImages] = useState<Record<string, string>>({});

  const load = () => api<{ marketing_consent: boolean; items: Offer[] }>("/inbox").then((r) => { setItems(r.items); setConsent(r.marketing_consent); });
  useEffect(() => { load(); }, []);
  useEffect(() => {
    items.filter((o) => !o.seen_at).forEach((o) => api(`/inbox/${o.id}/seen`, { method: "POST" }).catch(() => {}));
    items.filter((o) => o.has_image && !images[o.id]).forEach(async (o) => {
      const blob = await api<Blob>(`/inbox/${o.id}/image`).catch(() => null);
      if (blob) setImages((m) => ({ ...m, [o.id]: URL.createObjectURL(blob) }));
    });
  }, [items]);

  return (
    <>
      <div className="head"><div><h1>Offers</h1><div className="mute">Offers you agreed to receive. At most a few a week.</div></div></div>
      {!consent && <div className="banner info" style={{ marginBottom: 16 }}>Offers are off. You can turn them on in Privacy & memory.</div>}
      {items.length === 0 ? <div className="card empty">No offers right now.</div> : (
        <div className="grid g3">
          {items.map((o) => (
            <div className="card" key={o.id}>
              {images[o.id] && <img src={images[o.id]} alt="" style={{ width: "100%", borderRadius: 10, marginBottom: 10 }} />}
              <b>{o.title}</b>
              <p className="small">{o.body}</p>
              <div className="row">
                {o.cta_label && <button className="btn sm primary" onClick={async () => {
                  const r = await api<{ url: string | null }>(`/inbox/${o.id}/click`, { method: "POST" });
                  if (r.url) window.open(r.url, "_blank", "noopener");
                }}>{o.cta_label}</button>}
                <span className="spacer" />
                <button className="btn sm ghost" onClick={async () => { await api(`/inbox/${o.id}`, { method: "DELETE" }); load(); }}>Dismiss</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
