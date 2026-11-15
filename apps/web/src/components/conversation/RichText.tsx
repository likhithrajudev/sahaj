import { CITATION_TAG, MASK_TAG, type Citation } from "@sahaj/contracts";
import { Lock } from "lucide-react";
import type { ReactNode } from "react";

const TOKEN = new RegExp(`${CITATION_TAG.source}|${MASK_TAG.source}`, "g");
const FIELD_LABEL: Record<string, string> = {
  PAN: "PAN", AADHAAR: "Aadhaar", PHONE: "Phone", EMAIL: "Email", UPI: "UPI ID", ACCOUNT: "Account no.",
};

/** Renders citation tags as numbered chips and masked identifiers as "hidden" pills. */
export function RichText({ text, citations = [], onCite }: { text: string; citations?: Citation[]; onCite?: (c: Citation) => void }) {
  const out: ReactNode[] = [];
  const order = citations.map((c) => c.id);
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    const start = m.index ?? 0;
    // drop the space before a citation so the chip hugs the word, like a footnote
    const before = text.slice(last, start);
    out.push(m[1] ? before.replace(/\s+$/, "") : before);
    if (m[1]) {
      const n = order.indexOf(m[1]) + 1;
      const c = citations.find((x) => x.id === m[1]);
      out.push(
        <button key={start} type="button" onClick={() => c && onCite?.(c)} disabled={!c}
          className="mx-0.5 inline-flex h-5 min-w-5 -translate-y-1 items-center justify-center rounded-full bg-primary/10 px-1 text-[11px] font-semibold text-primary"
          aria-label={`Source ${n || "unavailable"}`}>
          {n || "?"}
        </button>,
      );
    } else {
      out.push(
        <span key={start} className="mx-0.5 inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
          <Lock className="size-3" aria-hidden /> {FIELD_LABEL[m[2]] ?? m[2]} hidden
        </span>,
      );
    }
    last = start + m[0].length;
  }
  out.push(text.slice(last));
  return <>{out}</>;
}
