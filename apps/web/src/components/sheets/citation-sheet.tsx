import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/ui/icon";
import { openDocument } from "./document-workflows";
import { Sheet } from "@/components/ui/sheet";
import { useT } from "@/lib/i18n";
import { clean, cn, withRupeeSign } from "@/lib/utils";
import { useSession } from "@/store/session";
import { closeSheet, useSheet, useUi } from "@/store/ui";

export function CitationSheet() {
  const t = useT();
  const { open } = useSheet("citations");
  const target = useUi((s) => s.citation);
  const item = useSession((s) => s.timeline.find((i) => i.id === target?.itemId));
  const citations = item?.kind === "assistant" ? item.citations : [];
  const docs = [...new Set(citations.map((c) => clean(c.doc)))];
  const [previewError, setPreviewError] = useState("");
  const highlighted = useRef<HTMLLIElement>(null);
  useEffect(() => {
    setPreviewError("");
    if (!open) return;
    const timer = setTimeout(() => { void highlighted.current?.scrollIntoView({ block: "nearest" }); }, 350);
    return () => clearTimeout(timer);
  }, [open, target?.citationId]);

  return (
    <Sheet name="citations" onClose={closeSheet} label={t("sources")}>
      <div className="flex items-center justify-between">
        <h2 className="text-[22px] font-semibold">{t("sources")} · {citations.length}</h2>
        <button type="button" aria-label={t("close")} onClick={closeSheet} className="flex size-11 items-center justify-center rounded-full transition-colors hover:bg-surface-2">
          <Icon name="close" />
        </button>
      </div>
      {docs.length === 1 && (
        <p className="mt-2 flex items-center gap-2 text-sm text-ink-2">
          <Icon name="description" size={18} /> {docs[0]}
        </p>
      )}
      {previewError && <p role="alert" className="mt-2 text-error-ink">{previewError}</p>}
      <ol className="mt-4 flex flex-col gap-3 pb-4">
        {citations.map((c, i) => {
          const active = c.id === target?.citationId;
          return (
            <li key={c.id} ref={active ? highlighted : undefined}
              className={cn("rounded-2xl p-4 transition-colors", active ? "bg-primary-soft ring-[1.5px] ring-primary" : "bg-surface-muted")}>
              <div className="flex items-center gap-2 text-sm font-semibold">
                <span className={cn("flex size-[22px] items-center justify-center rounded-md text-xs font-bold",
                  active ? "bg-primary text-on-primary" : "bg-surface-2 text-primary")}>{i + 1}</span>
                <span className={active ? "text-primary" : "text-ink-2"}>
                  {docs.length > 1 && <>{clean(c.doc)} · </>}
                  {c.clause ? `${t("clause")} ${c.clause}` : clean(c.doc)}
                  {active && <> · {t("cited")}</>}
                </span>
              </div>
              {c.file_id && c.page && <button type="button" className="min-h-11 text-primary underline"
                onClick={() => {
                  setPreviewError("");
                  void openDocument(`/files/${encodeURIComponent(c.file_id!)}?inline=true`, c.page)
                    .catch(() => setPreviewError("Couldn’t open the file. Check that it is still in Policy documents."));
                }}>Open PDF on page {c.page}</button>}
              {c.title && <h3 className="mt-2 text-lg font-semibold leading-6">{c.title}</h3>}
              <p dir="auto" className="mt-1.5 whitespace-pre-line text-[17px] leading-[25px] text-ink">{withRupeeSign(clean(c.body || c.text))}</p>
            </li>
          );
        })}
      </ol>
    </Sheet>
  );
}
