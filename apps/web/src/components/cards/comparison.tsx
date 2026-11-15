import type { ComparisonCard as Comparison } from "@sahaj/contracts";
import { useState } from "react";
import { Icon } from "@/components/ui/icon";
import { useT, type StringKey } from "@/lib/i18n";
import { clean, cn, sentenceCase, withRupeeSign } from "@/lib/utils";
import { CardShell } from "./shell";

const TITLE: Record<Comparison["goal"], StringKey> = {
  health: "compareHealth", term: "compareTerm", whole_life: "compareWholeLife",
};

/** Side-by-side table that swipes on phones (sticky first column), or a stacked per-attribute list. */
export function ComparisonCard({ card }: { card: Comparison }) {
  const t = useT();
  const [view, setView] = useState<"table" | "list">("table");
  const plans = card.plans.map((p) => ({ ...p, name: clean(p.name) }));
  const labels = plans[0]?.rows.map(([label]) => label) ?? [];
  const value = (planIdx: number, rowIdx: number) => withRupeeSign(sentenceCase(clean(plans[planIdx].rows[rowIdx]?.[1] ?? "—")));
  const initials = plans.map((p) => p.name[0]?.toUpperCase() ?? "?");

  return (
    <CardShell icon="compare_arrows" title={t(TITLE[card.goal] ?? "compareTitle", { n: plans.length })} flush>
      <div className="flex gap-1 px-[18px] pb-2" role="tablist">
        {(["table", "list"] as const).map((v) => (
          <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)}
            className={cn("h-8 rounded-full px-3 text-[13px] font-semibold", view === v ? "bg-primary-soft text-primary" : "text-ink-3")}>
            {t(v === "table" ? "viewTable" : "viewList")}
          </button>
        ))}
      </div>

      {view === "table" ? (
        <div className="scrollbar-none overflow-x-auto overscroll-x-contain">
          <table className="w-max min-w-full border-separate border-spacing-0 text-[15px] leading-[21px]">
            <thead>
              <tr>
                <th className="sticky left-0 z-10 w-[118px] border-b border-r border-line bg-surface" />
                {plans.map((p) => (
                  <th key={p.id} className="w-[150px] border-b border-line px-3 py-2.5 text-left align-top">
                    <span className="block text-[17px] font-semibold leading-[22px]">{p.name}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {labels.map((label, r) => (
                <tr key={label}>
                  <th scope="row" className="sticky left-0 z-10 w-[118px] border-b border-r border-line bg-surface py-2.5 pl-[18px] pr-2 text-left align-top text-sm font-normal text-ink-2">
                    {sentenceCase(label)}
                  </th>
                  {plans.map((p, i) => (
                    <td key={p.id} className="w-[150px] border-b border-line px-3 py-2.5 align-top">{value(i, r)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="px-[18px]">
          <div className="flex flex-wrap gap-1.5 pb-2">
            {plans.map((p, i) => (
              <span key={p.id} className="rounded-lg bg-surface-2 px-2.5 py-1 text-[13px] font-semibold text-primary">
                {initials[i]} · {p.name}
              </span>
            ))}
          </div>
          {labels.map((label, r) => (
            <div key={label} className="border-t border-line py-2.5">
              <div className="text-[15px] font-semibold">{sentenceCase(label)}</div>
              <div className="mt-1 grid gap-x-3 gap-y-1" style={{ gridTemplateColumns: `repeat(${Math.min(plans.length, 3)}, minmax(0, 1fr))` }}>
                {plans.map((p, i) => (
                  <span key={p.id} className="text-[15px] leading-[21px]">
                    <b className="font-bold text-primary">{initials[i]}</b> {value(i, r)}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <footer className="flex items-center justify-between px-[18px] py-3 text-[13px] text-ink-3">
        <span>{card.premiums_included ? t("premiumsIndicative") : " "}</span>
        {view === "table" && plans.length > 1 && (
          <span className="flex items-center gap-1">{t("swipeMore")} <Icon name="swipe_left" size={18} /></span>
        )}
      </footer>
    </CardShell>
  );
}
