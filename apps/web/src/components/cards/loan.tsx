import type { EmiResult, LoanCalculationCard, LoanInputs, PrepaymentResult } from "@sahaj/contracts";
import { motion, useReducedMotion } from "motion/react";
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
  const principalShare = result.total_payment ? inputs.principal / result.total_payment : 1;
  const principalPct = Math.round(principalShare * 100);
  return (
    <CardShell icon="calculate" iconClass="bg-loan-soft text-loan" title={t("emiTitle")}>
      <div className="grid grid-cols-3 gap-3 rounded-2xl bg-surface-muted px-3.5 py-3">
        <Stat label={t("loanAmount")} value={rupees(inputs.principal)} />
        <Stat label={t("rate")} value={`${inputs.annual_rate_percent}%`} />
        <Stat label={t("tenure")} value={`${inputs.tenure_months} ${t("months")}`} />
      </div>
      <div className="mt-4 flex flex-col gap-0.5">
        <span className="text-[15px] font-medium text-ink-2">{t("monthlyEmi")}</span>
        <span className="text-[40px] font-bold leading-[46px] tracking-[-0.02em] tabular-nums">{rupees(result.emi)}</span>
      </div>
      <div className="mt-4 flex items-center gap-5 border-t border-line pt-4">
        <Donut share={principalShare}
          label={`${t("principal")} ${principalPct}%, ${t("interest")} ${100 - principalPct}%`} />
        <dl className="flex min-w-0 flex-1 flex-col gap-2.5 text-[15px]">
          <Legend color="var(--loan)" label={t("principal")} value={rupees(inputs.principal)} pct={principalPct} />
          <Legend color="var(--accent)" label={t("interest")} value={rupees(result.total_interest)} pct={100 - principalPct} />
          <div className="flex items-baseline justify-between gap-2 border-t border-line pt-2.5">
            <dt className="text-ink-2">{t("totalPayment")}</dt>
            <dd className="font-semibold tabular-nums">{rupees(result.total_payment)}</dd>
          </div>
        </dl>
      </div>
      <LenderNote />
    </CardShell>
  );
}

function Legend({ color, label, value, pct }: { color: string; label: string; value: string; pct: number }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="flex min-w-0 items-center gap-2 text-ink-2">
        <span className="size-2.5 flex-none translate-y-[-1px] rounded-full" style={{ background: color }} />
        <span className="truncate">{label}</span>
      </dt>
      <dd className="flex-none font-semibold tabular-nums">{value} <span className="text-[13px] font-medium text-ink-3">{pct}%</span></dd>
    </div>
  );
}

/** Principal and interest as two arcs of one ring; it draws itself in when the card arrives. */
function Donut({ share, label }: { share: number; label: string }) {
  const reduce = useReducedMotion();
  const ease = [0.16, 1, 0.3, 1] as const;
  const gap = 0.012;
  return (
    <svg viewBox="0 0 100 100" className="size-[92px] flex-none -rotate-90" role="img" aria-label={label}>
      <circle cx="50" cy="50" r="38" fill="none" stroke="var(--surface-2)" strokeWidth="13" />
      <motion.circle cx="50" cy="50" r="38" fill="none" stroke="var(--loan)" strokeWidth="13" strokeLinecap="round"
        initial={reduce ? false : { pathLength: 0 }} animate={{ pathLength: Math.max(0, share - gap) }}
        transition={{ duration: 0.9, ease }} />
      <motion.circle cx="50" cy="50" r="38" fill="none" stroke="var(--accent)" strokeWidth="13" strokeLinecap="round"
        style={{ rotate: share * 360, originX: "50px", originY: "50px" }}
        initial={reduce ? false : { pathLength: 0 }} animate={{ pathLength: Math.max(0, 1 - share - gap) }}
        transition={{ duration: 0.6, delay: reduce ? 0 : 0.7, ease }} />
    </svg>
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
    <CardShell icon="savings" iconClass="bg-loan-soft text-loan" title={t("prepayTitle")}>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2.5 rounded-2xl bg-surface-muted px-3.5 py-3">
        <Stat label={t("outstanding")} value={rupees(inputs.principal)} />
        <Stat label={t("rate")} value={`${inputs.annual_rate_percent}%`} />
        <Stat label={t("monthsLeft")} value={inputs.tenure_months} />
        <Stat label={t("prepayment")} value={rupees(inputs.prepay_amount)} />
      </div>
      <div className="mt-3 flex items-end justify-between gap-3 rounded-2xl bg-success-soft px-4 py-4 text-success">
        <div className="flex flex-col">
          <span className="text-[15px] font-medium">{t("interestSaved")}</span>
          <span className="text-[36px] font-bold leading-[42px] tracking-[-0.02em] tabular-nums">{rupees(result.interest_saved)}</span>
        </div>
        {sameEmi ? (
          <div className="flex flex-col items-end">
            <span className="text-[15px] font-medium">{t("monthsSaved")}</span>
            <span className="text-[28px] font-bold leading-9 tabular-nums">{result.months_saved}</span>
          </div>
        ) : (
          <div className="flex flex-col items-end">
            <span className="text-[15px] font-medium">{t("emi")}</span>
            <span className="text-xl font-bold tabular-nums">−{rupees(result.emi_before - result.emi_after)}</span>
          </div>
        )}
      </div>
      <table className="mt-3 w-full text-[15px] tabular-nums">
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
              <th className="py-2.5 text-left font-normal text-ink-2">{label}</th>
              <td className="py-2.5 text-right text-ink-3">{before}</td>
              <td className="py-2.5 text-right font-semibold">{after}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex flex-col gap-1.5 text-[13px] leading-[18px] text-ink-3">
        <span className="flex gap-1.5"><Icon name="info" size={16} />{sameEmi ? t("sameEmi") : t("lowerEmi")}</span>
        <span>{t("lenderNote")}</span>
      </div>
    </CardShell>
  );
}
