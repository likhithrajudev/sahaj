import { CITATION_TAG, MASK_TAG, type Citation } from "@sahaj/contracts";
import type { ReactNode } from "react";
import { Icon } from "@/components/ui/icon";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const TOKEN = new RegExp(`${CITATION_TAG.source}|${MASK_TAG.source}`, "g");
const FIELD_LABEL: Record<string, string> = {
  PAN: "PAN", AADHAAR: "Aadhaar", PHONE: "Phone", EMAIL: "Email", UPI: "UPI ID", ACCOUNT: "Account",
};

/** Citation tags become numbered chips (44 px tap target); masked identifiers become "PAN hidden" pills. */
export function RichText({ text, citations = [], onCite, inverse = false }: {
  text: string; citations?: Citation[]; onCite?: (id: string) => void; inverse?: boolean;
}) {
  const t = useT();
  const out: ReactNode[] = [];
  const order = citations.map((c) => c.id);
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    const start = m.index ?? 0;
    const before = text.slice(last, start);
    last = start + m[0].length;
    if (m[1]) {
      // A citation hugs its word like a footnote: the last word, the chip and any punctuation after it
      // never wrap apart (no line starting with ". Some…").
      const trimmed = before.replace(/\s+$/, "");
      const word = trimmed.match(/\S+$/)?.[0] ?? "";
      const punct = text.slice(last).match(/^[.,;:!?)\]।]+/)?.[0] ?? "";
      last += punct.length;
      out.push(trimmed.slice(0, trimmed.length - word.length));
      const n = order.indexOf(m[1]) + 1;
      out.push(
        <span key={start} className="whitespace-nowrap">
          {word}
          <button type="button" onClick={() => n && onCite?.(m[1])} disabled={!n}
            aria-label={`${t("source")} ${n}`}
            className="relative mx-0.5 inline-flex -translate-y-1.5 align-baseline before:absolute before:-inset-3 before:content-['']">
            <span className="flex h-[18px] min-w-[18px] items-center justify-center rounded-[5px] bg-primary-soft px-1 text-[11px] font-bold leading-none text-primary">
              {n || "?"}
            </span>
          </button>
          {punct}
        </span>,
      );
    } else {
      out.push(before);
      out.push(
        <span key={start} className={cn("mx-0.5 inline-flex h-6 items-center gap-1 rounded-md px-1.5 align-middle text-[13px] font-semibold",
          inverse ? "bg-white/15 text-white" : "bg-toast text-toast-ink")}>
          <Icon name="lock" size={14} /> {FIELD_LABEL[m[2]] ?? m[2]} {t("hidden")}
        </span>,
      );
    }
  }
  out.push(text.slice(last));
  return <>{out}</>;
}
