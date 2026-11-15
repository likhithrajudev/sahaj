import type { Citation } from "@sahaj/contracts";
import { initialSession, nextId, useSession, type SessionState, type TimelineItem } from "@/store/session";
import { useUi } from "@/store/ui";

/**
 * Development only: `?preview=<scene>` fills the conversation with the brief's sample content so every screen can be
 * seen without signing in or speaking. Scenes: signin, welcome, conversation, thinking, recording, speaking, handoff, consent,
 * kyc (booked), kyc-waiting (requested), kyc-consent (the permission card), kyc-sheet (the request sheet).
 */
export type PreviewScene = "signin" | "welcome" | "conversation" | "thinking" | "recording" | "speaking" | "handoff" | "consent"
  | "kyc" | "kyc-waiting" | "kyc-consent" | "kyc-sheet";

const KYC_PROMPT = {
  type: "consent_required" as const, purpose: "video_kyc" as const, title: "Video identity verification", version: "2026-11-draft-2",
  required: false, requires: null, withdrawal: "Future Sahaj appointment requests stop. The regulated provider manages records it already holds.",
  text: "With your permission, Sahaj will create a case so the service team can arrange a video identity-check appointment. An authorised official of the relevant regulated entity must conduct the live verification and may record the session or capture your photo and documents under that entity's process. Sahaj does not conduct the identity check. This request does not guarantee a loan or insurance approval. You can withdraw this consent for future appointments; records already held by the provider are subject to that provider's retention rules.",
};

function kycCaseView(booked: boolean) {
  const slot = new Date(Date.now() + 26 * 3_600_000);
  slot.setMinutes(30, 0, 0);
  return {
    id: "case-preview", reference: "a41f9c02be17", kind: "video_kyc" as const, priority: "normal" as const,
    status: booked ? "with_executive" as const : "waiting" as const,
    scheduled_for: booked ? slot.toISOString() : null, meeting_url: booked ? "https://meet.example.com/kyc-a41f" : null,
  };
}

const LOTUS: Citation = {
  id: "health-lotus-care:3.2", doc: "Lotus Care (SAMPLE)", clause: "3.2", title: "Pre-existing diseases",
  text: "3.2 Pre-existing diseases. Expenses related to a pre-existing disease are covered after 36 months of continuous coverage.",
  body: "Expenses related to a pre-existing disease are covered after 36 months of continuous coverage from the first policy start date.",
};
const NEEM: Citation = {
  id: "health-neem-essential:4.1", doc: "Neem Essential (SAMPLE)", clause: "4.1", title: "Waiting periods",
  text: "4.1 Waiting periods. Pre-existing diseases are covered after 48 months.",
  body: "Pre-existing diseases are covered after 48 months of continuous coverage. Specified illnesses carry a 24 month wait.",
};

const assistant = (patch: Partial<Extract<TimelineItem, { kind: "assistant" }>>): Omit<Extract<TimelineItem, { kind: "assistant" }>, "id"> => ({
  kind: "assistant", agent: "insurance", text: "", citations: [], traceId: "preview", replyKind: "answer", fallback: false,
  audioUrl: null, audioSeconds: null, textOnly: false, verification: null, suggestions: [], feedback: null, ...patch,
});

function conversation(): Omit<TimelineItem, "id">[] {
  return [
    { kind: "system", icon: "verified_user", text: "consentGranted", tone: "success" },
    { kind: "user", text: "What is the waiting period for pre-existing diseases?" },
    assistant({
      text: "Lotus Care covers pre-existing diseases after 36 months [health-lotus-care:3.2]. Neem Essential waits longer, 48 months [health-neem-essential:4.1].",
      citations: [LOTUS, NEEM], verification: { level: "verified", sources: 2, from_cache: false, checks: ["guardrails", "fact_check"] },
      audioSeconds: 9,
    }),
    { kind: "user", text: "Which health insurance should I buy for my family?" },
    {
      kind: "card",
      traceId: "preview",
      card: {
        type: "profile_summary",
        details: [
          "Health insurance", "Eldest person covered: 34", "Yearly income: 1200000", "Metro city", "Family with 2 children",
          "No existing health insurance", "No existing medical condition", "Wants maternity cover", "Priority: lowest premium",
        ],
      },
    },
    assistant({ agent: "advice", replyKind: "confirm", text: "Is that right, or should anything change?" }),
    { kind: "user", text: "Yes, that is correct." },
    {
      kind: "card",
      traceId: "preview",
      card: {
        type: "recommendation", goal: "health", sample_data: true, indicative_premiums: true,
        suggested_cover: { amount: 2000000, basis: "about 1.5 times yearly income for a metro family of four, rounded up", note: "Maternity cover needs a plan with a maternity benefit." },
        plans: [
          {
            rank: 1, product_id: "peepal", name: "Peepal Family (SAMPLE)", insurer: "Sample Health Co.", cover: 2000000, annual_premium: 24800,
            highlights: ["Maternity cover after 24 months", "No room rent limit", "Restores cover once a year"],
            reasons: ["covers maternity", "lowest premium of the matched plans"], meets_suggested_cover: true,
            criteria: {
              premium: { value: 24800, score: 0.92, weight: 0.4, contribution: 0.37 },
              claim_ratio: { value: 0.94, score: 0.8, weight: 0.2, contribution: 0.16 },
              ped_waiting: { value: 36, score: 0.7, weight: 0.2, contribution: 0.14 },
              network: { value: 7400, score: 0.85, weight: 0.2, contribution: 0.17 },
            },
          },
          {
            rank: 2, product_id: "lotus", name: "Lotus Care (SAMPLE)", insurer: "Sample Health Co.", cover: 1500000, annual_premium: 21200,
            highlights: ["Pre-existing diseases after 36 months", "Day-care procedures covered"],
            reasons: [], meets_suggested_cover: false,
            criteria: {
              premium: { value: 21200, score: 1, weight: 0.4, contribution: 0.4 },
              claim_ratio: { value: 0.91, score: 0.6, weight: 0.2, contribution: 0.12 },
              ped_waiting: { value: 36, score: 0.7, weight: 0.2, contribution: 0.14 },
              network: { value: 6100, score: 0.6, weight: 0.2, contribution: 0.12 },
            },
          },
          {
            rank: 3, product_id: "neem", name: "Neem Essential (SAMPLE)", insurer: "Sample Assurance", cover: 2000000, annual_premium: 27900,
            highlights: ["Large hospital network", "No co-payment"],
            reasons: [], meets_suggested_cover: true,
            criteria: {
              premium: { value: 27900, score: 0.6, weight: 0.4, contribution: 0.24 },
              claim_ratio: { value: 0.96, score: 1, weight: 0.2, contribution: 0.2 },
              ped_waiting: { value: 48, score: 0.4, weight: 0.2, contribution: 0.08 },
              network: { value: 9800, score: 1, weight: 0.2, contribution: 0.2 },
            },
          },
        ],
        disclosures: [
          "These are sample plans, not real products.",
          "Premiums are indicative and change with age, city and health.",
          "Sahaj does not sell insurance or earn commission.",
          "Read the policy wording before you buy.",
          "A ranking is not advice to buy a particular plan.",
        ],
        disclosures_version: "2026-11-draft-1",
      },
    },
    assistant({
      agent: "advice", replyKind: "recommendation",
      text: "The suggested cover is ₹20 lakh. The plan that matched best is Peepal Family (SAMPLE). The full details are on the screen.",
      verification: { level: "engine", sources: 0, from_cache: false, checks: ["guardrails"] }, audioSeconds: 12,
    }),
    { kind: "user", text: "Compare the Lotus and Neem health plans" },
    {
      kind: "card",
      traceId: "preview",
      card: {
        type: "comparison", goal: "health", sample_data: true, premiums_included: true,
        plans: [
          { id: "lotus", name: "Lotus Care (SAMPLE)", insurer: "Sample Health Co.", rows: [
            ["pre-existing disease wait", "36 months"], ["co-payment", "none"], ["room rent", "single private room"],
            ["maternity", "not covered"], ["restoration of cover", "once a year"], ["no-claim bonus", "10% a year, up to 50%"],
            ["network hospitals", "6,100"], ["indicative yearly premium for the suggested cover", "21200"],
          ] },
          { id: "neem", name: "Neem Essential (SAMPLE)", insurer: "Sample Assurance", rows: [
            ["pre-existing disease wait", "48 months"], ["co-payment", "none"], ["room rent", "no limit"],
            ["maternity", "after 36 months"], ["restoration of cover", "unlimited"], ["no-claim bonus", "20% a year, up to 100%"],
            ["network hospitals", "9,800"], ["indicative yearly premium for the suggested cover", "27900"],
          ] },
        ],
      },
    },
    assistant({
      text: "Lotus Care has the shorter wait for pre-existing diseases [health-lotus-care:3.2]; Neem Essential has the bigger hospital network and covers maternity [health-neem-essential:4.1].",
      citations: [LOTUS, NEEM], verification: { level: "verified", sources: 2, from_cache: false, checks: ["guardrails", "fact_check"] },
      audioSeconds: 11,
    }),
    { kind: "user", text: "What would the EMI be on 5 lakh at 11% for 3 years?" },
    {
      kind: "card",
      traceId: "preview",
      card: {
        type: "loan_calculation", kind: "emi",
        inputs: { principal: 500000, annual_rate_percent: 11, tenure_months: 36 },
        result: { emi: 16369, total_payment: 589300, total_interest: 89300 },
      },
    },
    assistant({
      agent: "loan", replyKind: "calc",
      text: "Your EMI would be about ₹16,369 a month. Over 3 years you would pay about ₹89,300 in interest.",
      verification: { level: "engine", sources: 0, from_cache: false, checks: ["guardrails"] }, audioUrl: "data:,", audioSeconds: 8,
      suggestions: ["Can I repay my loan early without a penalty?", "What if the tenure is 5 years?", "Talk about home loans"],
    }),
  ] as Omit<TimelineItem, "id">[];
}

export function seedPreview(scene: PreviewScene) {
  const granted = { state: "granted" as const, version: "2026-11-draft-1", at: Date.now() };
  const base: SessionState = {
    ...initialSession,
    connection: "open",
    sessionId: "sess_7f3k92",
    consent: { ...initialSession.consent, conversation: granted, needs_analysis: granted },
  };
  const empty = scene === "welcome" || scene === "consent" || scene.startsWith("kyc");
  const timeline = empty ? [] : conversation().map((i) => ({ ...i, id: nextId() }) as TimelineItem);
  const state: SessionState = { ...base, timeline };
  if (scene === "kyc" || scene === "kyc-waiting" || scene === "kyc-consent") {
    timeline.push({ id: nextId(), kind: "user", text: "Book my video KYC" });
    timeline.push({ id: nextId(), ...assistant({ agent: "general", text: "I can ask our team to book your video KYC appointment. First, please read and agree to the permission below." }) } as TimelineItem);
    timeline.push({ id: nextId(), kind: "consent", prompt: KYC_PROMPT, answered: scene === "kyc-consent" ? null : true });
  }
  if (scene === "kyc" || scene === "kyc-waiting") {
    const booked = scene === "kyc";
    timeline.push({ id: nextId(), kind: "system", icon: "verified_user", text: "kycGranted", tone: "success" });
    if (booked) timeline.push({ id: nextId(), kind: "system", icon: "support_agent", text: "agentJoined", tone: "success", vars: { name: "Ravi" } });
    Object.assign(state, {
      consent: { ...state.consent, video_kyc: { state: "granted", version: KYC_PROMPT.version, at: Date.now() } },
      handoff: { reference: "a41f9c02be17", reason: "video_kyc", case: kycCaseView(booked), agentName: booked ? "Ravi" : null },
    });
  }
  if (scene === "kyc-sheet") useUi.setState({ sheet: "kyc", sheetStack: [] });
  if (scene === "thinking") Object.assign(state, { turn: "thinking", status: "checking", statusHistory: ["transcribing", "thinking", "searching", "checking"] });
  if (scene === "recording") Object.assign(state, { turn: "recording", recordingSince: Date.now(), level: 0.4 });
  if (scene === "speaking") Object.assign(state, { turn: "speaking", speaking: { elapsed: 3.2, duration: 8 } });
  if (scene === "handoff") Object.assign(state, { handoff: { reference: "SAH-7F3K-92", reason: "user_requested", case: null, agentName: null } });
  if (scene === "consent") Object.assign(state, {
    consent: initialSession.consent,
    consentPrompt: {
      type: "consent_required", purpose: "conversation", title: "Before we talk", version: "2026-11-draft-1", required: true, requires: null,
      withdrawal: "Sahaj will stop processing what you say.",
      text: "Sahaj will process your voice and what you share to answer your questions about insurance and loans. Personal identifiers such as PAN and Aadhaar are masked before anything is stored. A record of the conversation is kept for audit. You can withdraw this permission at any time from the menu.",
    },
  });
  useSession.setState(state, true);
}

export const previewScene = (): PreviewScene | null =>
  (new URLSearchParams(location.search).get("preview") as PreviewScene | null) || null;
