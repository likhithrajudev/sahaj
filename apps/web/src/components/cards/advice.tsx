import type { ConsentRequiredEvent, ProfileSummaryCard, RecommendationCard, RecommendedPlan } from "@sahaj/contracts";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { isStringKey, useT, type StringKey, type UiLang } from "@/lib/i18n";
import { answerConsent, cancelHandoff } from "@/lib/session";
import { clean, cn, rupees, rupeesWords, sentenceCase, withRupeeSign } from "@/lib/utils";
import { useUi } from "@/store/ui";

export function ProfileSummary({ card }: { card: ProfileSummaryCard }) {
  const t = useT();
  return (
    <section className="rounded-[20px] border border-line bg-surface px-[18px] pb-4 pt-[18px]">
      <h3 className="flex items-center gap-2 text-[19px] font-semibold leading-[26px]">
        <Icon name="person_check" size={22} className="text-primary" /> {t("understood")}
      </h3>
      <ul className="mt-2">
        {card.details.map((d) => (
          <li key={d} dir="auto" className="border-b border-line py-2.5 text-[17px] leading-6 last:border-b-0">
            {withRupeeSign(sentenceCase(clean(d)))}
          </li>
        ))}
      </ul>
      <p className="mt-3 text-sm font-semibold text-ink-2">{t("sayOne")}</p>
      <div className="mt-2 flex flex-col items-start gap-2">
        <Hint icon="check" iconClass="text-success">{t("sayYes")}</Hint>
        <Hint icon="edit" iconClass="text-primary">{t("sayChange")}</Hint>
      </div>
    </section>
  );
}

function Hint({ icon, iconClass, children }: { icon: string; iconClass: string; children: string }) {
  return (
    <span className="flex items-center gap-2 rounded-xl border border-dashed border-line-2 px-3 py-2 text-[15px]">
      <Icon name={icon} size={18} className={iconClass} /> {children}
    </span>
  );
}

const CRITERIA: Record<string, [string, string]> = {
  premium: ["Premium", "प्रीमियम"],
  claim_ratio: ["Claims record", "क्लेम रिकॉर्ड"],
  features: ["Riders", "राइडर"],
  paying_term: ["Paying term", "भुगतान अवधि"],
  ped_waiting: ["Pre-existing wait", "पुरानी बीमारी प्रतीक्षा"],
  cost_sharing: ["Co-pay, room rent", "को-पे, रूम रेंट"],
  restoration_bonus: ["Restore, bonus", "रीस्टोर, बोनस"],
  network: ["Hospitals", "अस्पताल"],
};
const criterionLabel = (key: string, lang: UiLang) =>
  CRITERIA[key]?.[lang === "hi" ? 1 : 0] ?? sentenceCase(key.replace(/_/g, " "));

export function Recommendation({ card }: { card: RecommendationCard }) {
  const t = useT();
  const [how, setHow] = useState(false);
  const [open, setOpen] = useState<Record<number, boolean>>({ 0: true });
  const n = card.plans.length;

  return (
    <section className="overflow-hidden rounded-[20px] border border-line bg-surface">
      <div className="flex flex-col gap-3.5 px-[18px] pb-4 pt-[18px]">
        <div className="flex flex-wrap items-center gap-2">
          <Icon name="health_and_safety" size={20} className="text-primary" />
          <h3 className="flex-1 text-[15px] font-semibold">{t("planSuggestions")}</h3>
          {card.indicative_premiums && <Badge>{t("indicativePremiums")}</Badge>}
        </div>

        <div className="flex flex-col gap-1 rounded-2xl bg-primary-soft px-4 py-3.5">
          <span className="text-sm font-medium text-primary">{t("suggestedCover")}</span>
          <div className="flex flex-wrap items-baseline gap-2.5">
            <span className="text-[34px] font-bold leading-10 tracking-[-0.01em] text-primary-strong">{rupees(card.suggested_cover.amount)}</span>
            <span className="text-base text-primary">{rupeesWords(card.suggested_cover.amount)}</span>
          </div>
          <button type="button" onClick={() => setHow(!how)} aria-expanded={how}
            className="flex min-h-10 items-center gap-1 self-start text-[15px] font-semibold text-primary">
            {t("howWorked")} <Icon name={how ? "expand_less" : "expand_more"} size={20} />
          </button>
          <Collapse open={how}>
            <div className="flex flex-col gap-2 border-t border-line pt-2.5 text-[15px] leading-[22px]">
              <div><b className="font-semibold">{t("basis")}</b> {withRupeeSign(sentenceCase(card.suggested_cover.basis))}.</div>
              {card.suggested_cover.note && <div><b className="font-semibold">{t("note")}</b> {card.suggested_cover.note}</div>}
            </div>
          </Collapse>
        </div>

        {n > 0 && (
          <div className="flex items-center gap-2 text-[15px] font-medium text-success">
            <Icon name="task_alt" size={20} /> {n === 1 ? t("planMatched") : t("plansMatched", { n })}
          </div>
        )}
      </div>

      {n === 0 ? (
        <div className="mx-[18px] mb-4 flex gap-3 rounded-2xl border border-dashed border-line-2 p-4">
          <Icon name="search_off" size={22} className="text-ink-2" />
          <div>
            <div className="text-[15px] font-semibold">{t("noPlansTitle")}</div>
            <div className="text-sm leading-5 text-ink-2">{t("noPlansBody")}</div>
          </div>
        </div>
      ) : (
        card.plans.map((p, i) => (
          <PlanRow key={p.product_id} plan={p} open={!!open[i]} onToggle={() => setOpen((o) => ({ ...o, [i]: !o[i] }))} />
        ))
      )}

      <div className="flex flex-col gap-2.5 border-t border-line bg-surface-muted px-[18px] pb-[18px] pt-4">
        <h4 className="flex items-center gap-1.5 text-[15px] font-semibold">
          <Icon name="info" size={18} className="text-primary" /> {t("beforeDecide")}
        </h4>
        <ol className="flex flex-col gap-2">
          {card.disclosures.map((d, i) => (
            <li key={d} className="grid grid-cols-[20px_1fr] gap-1.5 text-[15px] leading-[21px]">
              <span className="font-semibold text-ink-3">{i + 1}</span><span>{clean(d)}</span>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function PlanRow({ plan, open, onToggle }: { plan: RecommendedPlan; open: boolean; onToggle: () => void }) {
  const t = useT();
  const lang = useUi((s) => s.lang);
  const name = clean(plan.name);
  const insurer = clean(plan.insurer);
  const scores = Object.entries(plan.criteria);
  return (
    <div className="flex flex-col gap-3 border-t border-line px-[18px] py-4">
      <div className="flex items-start gap-3">
        <span className="flex size-8 flex-none items-center justify-center rounded-full border-[1.5px] border-primary text-[15px] font-bold text-primary">
          {plan.rank}
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <div className="text-lg font-semibold leading-[22px]">
            {name}
          </div>
          <div className="text-sm text-ink-2">{insurer}</div>
          <div className={cn("mt-1 flex items-center gap-1 text-[13px] font-semibold", plan.meets_suggested_cover ? "text-success" : "text-warn")}>
            <Icon name={plan.meets_suggested_cover ? "task_alt" : "remove_moderator"} size={16} />
            {t(plan.meets_suggested_cover ? "meetsCover" : "belowCover")}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2.5 rounded-xl bg-bg px-3.5 py-3">
        <div className="flex flex-col gap-0.5">
          <span className="text-[13px] text-ink-3">{t("cover")}</span>
          <span className="text-lg font-semibold">{rupees(plan.cover)}</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-[13px] text-ink-3">{t("indicativePremium")}</span>
          <span className="text-lg font-semibold">{rupees(plan.annual_premium)}<span className="text-[13px] font-medium text-ink-3"> {t("perYear")}</span></span>
        </div>
      </div>
      <Collapse open={open}>
        <div className="flex flex-col gap-3.5">
          {plan.highlights.length > 0 && (
            <ul className="flex flex-col gap-1.5">
              {plan.highlights.map((h) => (
                <li key={h} className="flex gap-2 text-[15px] leading-[21px]">
                  <Icon name="check" size={18} className="text-primary" />{withRupeeSign(sentenceCase(clean(h)))}
                </li>
              ))}
            </ul>
          )}
          {plan.reasons.length > 0 && (
            <div className="flex flex-col gap-1">
              <span className="text-sm font-semibold">{t("whyRanks")}</span>
              <span className="text-[15px] leading-[22px] text-ink-2">{clean(sentenceCase(plan.reasons.join("; ")))}.</span>
            </div>
          )}
          {scores.length > 0 && (
            <div className="flex flex-col gap-2">
              <span className="text-sm font-semibold">{t("scoreBy")}</span>
              {scores.map(([key, s]) => {
                const v = Math.round(s.score * 10);
                return (
                  <div key={key} className="grid grid-cols-[118px_1fr_34px] items-center gap-2.5 text-sm">
                    <span className="text-ink-2">{criterionLabel(key, lang)}</span>
                    <div className="h-2 overflow-hidden rounded bg-surface-2">
                      <div className="h-2 rounded bg-primary" style={{ width: `${v * 10}%` }} />
                    </div>
                    <span className="text-right font-semibold">{v}/10</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </Collapse>
      <button type="button" onClick={onToggle} aria-expanded={open}
        className="flex min-h-9 items-center gap-1 self-start text-sm font-semibold text-primary">
        {t(open ? "showLess" : "detailsScores")} <Icon name={open ? "expand_less" : "expand_more"} size={18} />
      </button>
    </div>
  );
}

function Collapse({ open, children }: { open: boolean; children: React.ReactNode }) {
  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }} className="overflow-hidden">
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** The needs-analysis permission, asked inside the conversation. */
/** A permission asked inside the conversation (personal details, and any other purpose the server asks for). */
export function NeedsConsentCard({ prompt, answered }: { prompt: ConsentRequiredEvent; answered: boolean | null }) {
  const t = useT();
  const needs = prompt.purpose === "needs_analysis";
  return (
    <section className={cn("rounded-[20px] border bg-surface p-[18px]", answered === null ? "border-primary" : "border-line opacity-80")}>
      <h3 className="flex items-center gap-3 text-[19px] font-semibold">
        <span className="flex size-10 items-center justify-center rounded-xl bg-surface-2 text-primary"><Icon name="badge" /></span>
        {needs ? t("consent2Title") : prompt.title}
      </h3>
      <p className="mt-3 whitespace-pre-line text-[17px] leading-[25px]">{prompt.text}</p>
      <p className="mt-2 text-[13px] text-ink-3">{t("consentNotice")} {prompt.version} · {needs ? t("purposeNeeds") : prompt.purpose.replace(/_/g, " ")}</p>
      {answered === null ? (
        <div className="mt-4 grid grid-cols-2 gap-3">
          <Button variant="outline" onClick={() => answerConsent(false, prompt.purpose)}>{t("notNow")}</Button>
          <Button onClick={() => answerConsent(true, prompt.purpose)}>{t("agree")}</Button>
        </div>
      ) : answered === false && needs ? (
        <p className="mt-3 flex gap-2 rounded-xl bg-info-soft px-3 py-2.5 text-sm leading-5 text-ink">
          <Icon name="info" size={18} className="text-info" /> {t("needsDeclined")}
        </p>
      ) : null}
    </section>
  );
}

export function HandoffCard({ reference, reason, agentName }: { reference: string; reason?: string; agentName: string | null }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(reference);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch { /* clipboard blocked: the number is selectable */ }
  };
  const body = reason && isStringKey(`handoff_${reason}`) ? (`handoff_${reason}` as StringKey) : "handoffDefault";
  return (
    <section className="flex flex-col gap-4 rounded-[20px] border border-line bg-surface p-5">
      <span className="flex size-14 items-center justify-center rounded-full bg-surface-2 text-primary"><Icon name="support_agent" size={30} /></span>
      <h3 className="text-[26px] font-semibold leading-[34px]">{t("handoffTitle")}</h3>
      <p className="text-[17px] leading-[25px] text-ink-2">{t(body)}</p>
      <div className="flex items-center justify-between gap-3 rounded-2xl bg-bg px-4 py-3.5">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="text-[13px] font-semibold text-ink-2">{t("reference")}</span>
          <span className="select-all truncate font-mono text-2xl font-medium tracking-wide">{reference}</span>
        </div>
        <button type="button" onClick={copy}
          className="flex h-11 flex-none items-center gap-1.5 rounded-xl border border-line-2 bg-surface px-3.5 text-sm font-semibold text-primary">
          <Icon name={copied ? "check" : "content_copy"} size={18} /> {t(copied ? "copied" : "copy")}
        </button>
      </div>
      <p className={cn("flex items-center gap-2 rounded-xl px-3 py-2.5 text-[15px] font-semibold",
        agentName ? "bg-success-soft text-success" : "bg-warn-soft text-warm-ink")} role="status">
        <Icon name={agentName ? "support_agent" : "timer"} size={20} />
        {agentName ? t("withAgent", { name: agentName }) : t("waitingForPerson")}
      </p>
      <p className="text-sm leading-5 text-ink-3">{t("handoffShared")} {t("talkToPersonHint")}</p>
      <Button variant="neutral" size="md" onClick={cancelHandoff}>{t("cancelHandoff")}</Button>
    </section>
  );
}
