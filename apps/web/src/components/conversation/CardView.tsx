import type { Card } from "@sahaj/contracts";
import { rupees } from "@/lib/utils";

/** Temporary card rendering: complete data, plain layout. Replace with the designed cards. */
export function CardView({ card }: { card: Card }) {
  const shell = "rounded-xl border bg-card p-4 text-sm shadow-sm";
  switch (card.type) {
    case "profile_summary":
      return (
        <section className={shell}>
          <h3 className="mb-2 font-semibold">Here's what I understood</h3>
          <ul className="list-disc space-y-1 pl-5">{card.details.map((d) => <li key={d}>{d}</li>)}</ul>
        </section>
      );
    case "recommendation":
      return (
        <section className={shell}>
          <Badges sample={card.sample_data} indicative={card.indicative_premiums} />
          <p className="text-muted-foreground">Suggested cover</p>
          <p className="text-2xl font-semibold tabular-nums">{rupees(card.suggested_cover.amount)}</p>
          <p className="mt-1 text-xs text-muted-foreground">{card.suggested_cover.basis}</p>
          {card.suggested_cover.note && <p className="mt-1 text-xs">{card.suggested_cover.note}</p>}
          <ol className="mt-4 space-y-3">
            {card.plans.map((p) => (
              <li key={p.product_id} className="rounded-lg border p-3">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-semibold">{p.rank}. {p.name}</span>
                  <span className="tabular-nums">{rupees(p.annual_premium)}/yr</span>
                </div>
                <p className="text-xs text-muted-foreground">{p.insurer} · cover {rupees(p.cover)}</p>
                <ul className="mt-2 list-disc pl-5 text-xs">{p.highlights.map((h) => <li key={h}>{h}</li>)}</ul>
                {p.reasons.length > 0 && <p className="mt-2 text-xs">Why it ranks here: {p.reasons.join("; ")}</p>}
              </li>
            ))}
          </ol>
          {card.plans.length === 0 && <p className="mt-3">No plan in the catalogue matched these needs.</p>}
          <ul className="mt-4 space-y-1 border-t pt-3 text-xs text-muted-foreground">
            {card.disclosures.map((d) => <li key={d}>{d}</li>)}
          </ul>
        </section>
      );
    case "comparison":
      return (
        <section className={shell}>
          <Badges sample={card.sample_data} indicative={card.premiums_included} />
          <div className="-mx-4 overflow-x-auto px-4">
            <table className="w-full min-w-[480px] text-left text-xs">
              <thead>
                <tr>
                  <th className="sticky left-0 bg-card py-2 pr-3" />
                  {card.plans.map((p) => <th key={p.id} className="py-2 pr-3 font-semibold">{p.name}</th>)}
                </tr>
              </thead>
              <tbody>
                {card.plans[0]?.rows.map(([label], i) => (
                  <tr key={label} className="border-t align-top">
                    <th className="sticky left-0 bg-card py-2 pr-3 font-medium text-muted-foreground">{label}</th>
                    {card.plans.map((p) => <td key={p.id} className="py-2 pr-3">{p.rows[i]?.[1]}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      );
    case "loan_calculation":
      if (card.kind === "emi") {
        return (
          <section className={shell}>
            <p className="text-muted-foreground">
              {rupees(card.inputs.principal)} at {card.inputs.annual_rate_percent}% for {card.inputs.tenure_months} months
            </p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{rupees(card.result.emi)}<span className="text-sm font-normal"> /month</span></p>
            <Rows rows={[["Total payment", rupees(card.result.total_payment)], ["Total interest", rupees(card.result.total_interest)]]} />
            <Footnote />
          </section>
        );
      }
      return (
        <section className={shell}>
          <p className="text-muted-foreground">Paying {rupees(card.inputs.prepay_amount)} extra now</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{rupees(card.result.interest_saved)} <span className="text-sm font-normal">interest saved</span></p>
          <Rows rows={[
            ["EMI", `${rupees(card.result.emi_before)} → ${rupees(card.result.emi_after)}`],
            ["Months left", `${card.result.months_before} → ${card.result.months_after} (${card.result.months_saved} fewer)`],
            ["Total interest", `${rupees(card.result.interest_before)} → ${rupees(card.result.interest_after)}`],
          ]} />
          <Footnote />
        </section>
      );
  }
}

function Badges({ sample, indicative }: { sample: boolean; indicative: boolean }) {
  return (
    <div className="mb-3 flex gap-2 text-[11px] font-medium">
      {sample && <span className="rounded-full bg-accent/30 px-2 py-0.5">Sample data</span>}
      {indicative && <span className="rounded-full bg-muted px-2 py-0.5">Indicative premiums</span>}
    </div>
  );
}

function Rows({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="mt-3 space-y-1">
      {rows.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-4"><dt className="text-muted-foreground">{k}</dt><dd className="tabular-nums">{v}</dd></div>
      ))}
    </dl>
  );
}

const Footnote = () => <p className="mt-3 text-xs text-muted-foreground">Your lender's own figure may differ slightly.</p>;
