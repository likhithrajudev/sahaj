import type { EmiResult, LoanCalculationCard, LoanInputs, PrepaymentResult } from "@sahaj/contracts";
import { Icon } from "@/components/ui/icon";
import { useT } from "@/lib/i18n";
import { rupees } from "@/lib/utils";
import { CardShell, LenderNote, Stat } from "./shell";

export function LoanCard({ card }: { card: LoanCalculationCard }) {
  return card.kind === "emi"
    ? <EmiCard inputs={card.inputs} result={card.result} />
    : <PrepaymentCard inputs={card.inputs} result={card.result} />;
}

function EmiCard({ inputs, result }: { inputs: LoanInputs; result: EmiResult }) {
  const t = useT();
  const principalShare = result.total_payment ? (inputs.principal / result.total_payment) * 100 : 100;
  const interestPct = inputs.principal ? Math.round((result.total_interest / inputs.principal) * 100) : 0;
  return (
    <CardShell icon="calculate" iconClass="text-loan" title={t("emiTitle")}>
      <div className="grid grid-cols-3 gap-2">
        <Stat label={t("loanAmount")} value={rupees(inputs.principal)} />
        <Stat label={t("rate")} value={`${inputs.annual_rate_percent}%`} />
        <Stat label={t("tenure")} value={`${inputs.tenure_months} ${t("months")}`} />
      </div>
      <div className="my-3.5 h-px bg-line" />
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[15px] text-ink-2">{t("monthlyEmi")}</span>
        <span className="text-[34px] font-bold leading-10 tracking-[-0.01em]">{rupees(result.emi)}</span>
      </div>
      <div className="mt-3 flex h-2 gap-0.5 overflow-hidden rounded-full" role="img"
        aria-label={`${t("principal")} ${Math.round(principalShare)}%, ${t("interest")} ${100 - Math.round(principalShare)}%`}>
        <span className="h-full rounded-l-full bg-loan" style={{ width: `${principalShare}%` }} />
        <span className="h-full flex-1 rounded-r-full bg-accent" />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Stat label={t("totalPayment")} value={rupees(result.total_payment)} />
        <Stat label={`${t("totalInterest")} (${interestPct}%)`} value={rupees(result.total_interest)} />
      </div>
      <LenderNote />
    </CardShell>
  );
}

function PrepaymentCard({ inputs, result }: { inputs: LoanInputs & { prepay_amount: number }; result: PrepaymentResult }) {
  const t = useT();
  const sameEmi = (inputs.mode ?? "reduce_tenure") === "reduce_tenure";
  const rows: [string, string, string][] = [
    [t("emi"), rupees(result.emi_before), rupees(result.emi_after)],
    [t("monthsRow"), String(result.months_before), String(result.months_after)],
    [t("interest"), rupees(result.interest_before), rupees(result.interest_after)],
  ];
  return (
    <CardShell icon="savings" iconClass="text-loan" title={t("prepayTitle")}>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-xl bg-bg px-3.5 py-3">
        <Stat label={t("outstanding")} value={rupees(inputs.principal)} />
        <Stat label={t("rate")} value={`${inputs.annual_rate_percent}%`} />
        <Stat label={t("monthsLeft")} value={inputs.tenure_months} />
        <Stat label={t("prepayment")} value={rupees(inputs.prepay_amount)} />
      </div>
      <div className="mt-3 flex items-end justify-between gap-3 rounded-2xl bg-success-soft px-4 py-3.5 text-success">
        <div className="flex flex-col">
          <span className="text-[15px] font-medium">{t("interestSaved")}</span>
          <span className="text-[34px] font-bold leading-10">{rupees(result.interest_saved)}</span>
        </div>
        {sameEmi ? (
          <div className="flex flex-col items-end">
            <span className="text-[15px] font-medium">{t("monthsSaved")}</span>
            <span className="text-[28px] font-bold leading-9">{result.months_saved}</span>
          </div>
        ) : (
          <div className="flex flex-col items-end">
            <span className="text-[15px] font-medium">{t("emi")}</span>
            <span className="text-xl font-bold">−{rupees(result.emi_before - result.emi_after)}</span>
          </div>
        )}
      </div>
      <table className="mt-3 w-full text-[15px]">
        <thead>
          <tr className="text-[13px] text-ink-3">
            <th className="py-1.5 text-left font-normal" />
            <th className="py-1.5 text-right font-normal">{t("before")}</th>
            <th className="py-1.5 text-right font-normal">{t("after")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, before, after]) => (
            <tr key={label} className="border-t border-line">
              <th className="py-2 text-left font-normal">{label}</th>
              <td className="py-2 text-right text-ink-2">{before}</td>
              <td className="py-2 text-right font-semibold">{after}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex gap-4 text-[13px] leading-[18px] text-ink-3">
        <span className="flex gap-1.5"><Icon name="info" size={16} />{sameEmi ? t("sameEmi") : t("lowerEmi")}</span>
        <span>{t("lenderNote")}</span>
      </div>
    </CardShell>
  );
}
