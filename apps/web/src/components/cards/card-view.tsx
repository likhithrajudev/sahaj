import { Icon } from "@/components/ui/icon";
import { useT } from "@/lib/i18n";
import { clean, rupees } from "@/lib/utils";
import type { ShownCard as Card } from "@/store/session";
import { useUi } from "@/store/ui";
import { ProfileSummary, Recommendation } from "./advice";
import { ComparisonCard } from "./comparison";
import { LoanCard } from "./loan";

export function CardView({ card }: { card: Card }) {
  switch (card.type) {
    case "profile_summary": return <ProfileSummary card={card} />;
    case "recommendation": return <Recommendation card={card} />;
    case "comparison": return <ComparisonCard card={card} />;
    case "loan_calculation": return <LoanCard card={card} />;
  }
}

/** Desktop: the timeline shows a one-line summary; the full card opens in the side panel. */
export function CardSummary({ card, itemId }: { card: Card; itemId: string }) {
  const t = useT();
  const { icon, title, sub } = summarise(card, t);
  return (
    <button type="button" onClick={() => useUi.setState({ panelItemId: itemId, panelOpen: true })}
      className="card group flex w-full items-center gap-3.5 px-4 py-3.5 text-left transition-shadow duration-200 hover:shadow-raised">
      <span className="flex size-10 flex-none items-center justify-center rounded-xl bg-primary-soft text-primary"><Icon name={icon} /></span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-[17px] font-semibold">{title}</span>
        <span className="truncate text-sm text-ink-2">{sub}</span>
      </span>
      <span className="flex flex-none items-center gap-1 text-sm font-semibold text-primary">
        {t("openInPanel")} <Icon name="arrow_forward" size={18} className="transition-transform duration-200 group-hover:translate-x-0.5" />
      </span>
    </button>
  );
}

function summarise(card: Card, t: ReturnType<typeof useT>): { icon: string; title: string; sub: string } {
  switch (card.type) {
    case "recommendation": {
      const top = card.plans[0];
      return {
        icon: "health_and_safety",
        title: `${t("planSuggestions")} · ${t("cover").toLowerCase()} ${rupees(card.suggested_cover.amount)}`,
        sub: top ? `${clean(top.name)} · ${rupees(top.annual_premium)} ${t("perYear")}` : t("noPlansTitle"),
      };
    }
    case "comparison":
      return { icon: "compare_arrows", title: t("compareTitle", { n: card.plans.length }), sub: card.plans.map((p) => clean(p.name)).join(" · ") };
    case "profile_summary":
      return { icon: "person_check", title: t("understood"), sub: card.details.slice(0, 3).join(" · ") };
    case "loan_calculation":
      return card.kind === "emi"
        ? { icon: "calculate", title: `${t("monthlyEmi")} ${rupees(card.result.emi)}`, sub: `${rupees(card.inputs.principal)} · ${card.inputs.annual_rate_percent}% · ${card.inputs.tenure_months} ${t("months")}` }
        : { icon: "savings", title: `${t("interestSaved")} ${rupees(card.result.interest_saved)}`, sub: `${t("prepayment")} ${rupees(card.inputs.prepay_amount)}` };
  }
}
