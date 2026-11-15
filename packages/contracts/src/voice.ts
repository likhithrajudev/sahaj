/**
 * Voice WebSocket protocol (`/ws/voice`).
 *
 * Source of truth is the backend, not the prose docs:
 *   events  apps/api/orchestrator/session.py
 *   cards   apps/api/advisory/flow.py (profile_summary, recommendation)
 *           apps/api/advisory/compare.py (comparison)
 *           apps/api/loan/flow.py + loan/calc.py (loan_calculation)
 *   consent apps/api/trust/consent.py
 * Update this file in the same change as any of those.
 */

// ---------------------------------------------------------------- shared

export type ConsentPurpose = "conversation" | "needs_analysis";
/** "advice" is the needs-analysis / recommendation flow. */
export type AgentName = "insurance" | "loan" | "general" | "advice";
export type HandoffReason = "user_requested" | "guardrail_failures" | "stuck_in_questions";
export type InsuranceGoal = "health" | "term" | "whole_life";

export interface Citation {
  /** Tag as it appears in the answer text without brackets, e.g. "health-lotus-care:3.2". */
  id: string;
  /** The full clause (or computed fact) the tag points to. */
  text: string;
  /** Document name for display, e.g. "Lotus Care (SAMPLE)", "Loan calculation". */
  doc: string;
  /** Clause number ("3.2") and title for document clauses; null for facts the code computed. */
  clause: string | null;
  title: string | null;
  /** The clause text without its number and title. */
  body: string;
}

/** What produced an assistant message. */
export type ReplyKind = "answer" | "ask" | "confirm" | "recommendation" | "compare" | "calc";

/** What the server is doing during a turn (for "Finding the right documents…" style hints). */
export type StatusStep = "understanding" | "searching" | "comparing" | "calculating" | "thinking" | "checking";

// ---------------------------------------------------------------- client -> server
// Audio: send one complete recording (max 30 s, webm/opus) as a binary frame, only after done/error/handoff.

export interface ConsentMessage {
  type: "consent";
  purpose: ConsentPurpose;
  granted: boolean;
}

export interface HandoffRequest {
  type: "handoff";
}

export type ClientMessage = ConsentMessage | HandoffRequest;

// ---------------------------------------------------------------- server -> client
// Binary frames are MP3 chunks of the spoken answer; join them in order and play on `done`.

export interface SessionEvent {
  type: "session";
  id: string;
}

export interface ConsentRequiredEvent {
  type: "consent_required";
  purpose: ConsentPurpose;
  version: string;
  /** Show verbatim with accept and decline actions. */
  text: string;
}

export interface ConsentStatusEvent {
  type: "consent";
  purpose: ConsentPurpose;
  status: "granted" | "revoked";
}

export interface UserEvent {
  type: "user";
  /** Transcript with identifiers already masked, e.g. "[PAN_1]". See MASK_TAG. */
  text: string;
}

export interface AssistantEvent {
  type: "assistant";
  agent: AgentName;
  /** Contains citation tags like "[health-lotus-care:3.2]". See CITATION_TAG. */
  text: string;
  citations: Citation[];
  trace_id: string;
  /** "ask" = Sahaj is asking a question (clarifying, or the next needs-analysis question). */
  kind: ReplyKind;
  /** True when the checks blocked the answer and this is the safe "I can't confirm that…" reply. */
  fallback: boolean;
  /** Needs analysis only: which question this is, for "Understanding your needs · 4 of 9". */
  progress?: { step: number; total: number };
}

/** Sent while a turn is being worked on, possibly several times. Ignore unknown steps. */
export interface StatusEvent {
  type: "status";
  step: StatusStep;
}

export interface DoneEvent {
  type: "done";
}

export interface HandoffEvent {
  type: "handoff";
  reference: string;
  /** Absent when the server repeats the reference because audio arrived after a handoff. */
  reason?: HandoffReason;
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

// ---------------------------------------------------------------- cards
// Sent as {type:"card"} just before the matching assistant message. Discriminate on `card.type`.

export interface ProfileSummaryCard {
  type: "profile_summary";
  /** Every detail Sahaj understood, as short lines. Must be displayed in full. */
  details: string[];
}

export interface CriterionScore {
  /** Raw value of the criterion for this plan (e.g. a premium or a ratio). */
  value: number;
  /** 0..1, normalised across the plans compared (1 = best). */
  score: number;
  /** 0..1, share of the total; weights sum to 1. */
  weight: number;
  /** score × weight. */
  contribution: number;
}

export interface RecommendedPlan {
  rank: number;
  product_id: string;
  name: string;
  insurer: string;
  cover: number;
  annual_premium: number;
  highlights: string[];
  /** May be empty: only criteria where this plan is strictly best. */
  reasons: string[];
  meets_suggested_cover: boolean;
  /** Keyed by criterion name. */
  criteria: Record<string, CriterionScore>;
}

export interface RecommendationCard {
  type: "recommendation";
  goal: InsuranceGoal;
  sample_data: boolean;
  indicative_premiums: boolean;
  suggested_cover: {
    /** Rupees. 0 when no extra cover is needed. */
    amount: number;
    /** How the amount was worked out, in words. */
    basis: string;
    note: string | null;
  };
  /** Up to 3, ranked. May be empty when nothing matched. */
  plans: RecommendedPlan[];
  /** Fixed text. Always show all of them. */
  disclosures: string[];
  disclosures_version: string;
}

export interface ComparedPlan {
  id: string;
  name: string;
  insurer: string;
  rows: [label: string, value: string][];
}

export interface ComparisonCard {
  type: "comparison";
  goal: InsuranceGoal;
  plans: ComparedPlan[];
  sample_data: boolean;
  /** True when a row "indicative yearly premium for the suggested cover" is included. */
  premiums_included: boolean;
}

export type RepaymentMode = "reduce_tenure" | "reduce_emi";

export interface LoanInputs {
  /** Loan amount, or the outstanding amount for a prepayment. Rupees. */
  principal: number;
  annual_rate_percent: number;
  tenure_months: number;
  prepay_amount?: number;
  mode?: RepaymentMode;
}

export interface EmiResult {
  emi: number;
  total_payment: number;
  total_interest: number;
}

export interface PrepaymentResult {
  emi_before: number;
  emi_after: number;
  months_before: number;
  months_after: number;
  months_saved: number;
  interest_before: number;
  interest_after: number;
  interest_saved: number;
}

export type LoanCalculationCard =
  | { type: "loan_calculation"; kind: "emi"; inputs: LoanInputs; result: EmiResult }
  | { type: "loan_calculation"; kind: "prepayment"; inputs: LoanInputs & { prepay_amount: number }; result: PrepaymentResult };

export type Card = ProfileSummaryCard | RecommendationCard | ComparisonCard | LoanCalculationCard;
export type CardType = Card["type"];

/** The turn kind that produced the card. Prefer `card.type` for rendering. */
export type TurnKind = "confirm" | "recommendation" | "compare" | "calc";

export interface CardEvent {
  type: "card";
  kind: TurnKind;
  card: Card;
  trace_id: string;
}

// ---------------------------------------------------------------- unions

export type ServerEvent =
  | SessionEvent
  | ConsentRequiredEvent
  | ConsentStatusEvent
  | CardEvent
  | UserEvent
  | AssistantEvent
  | DoneEvent
  | HandoffEvent
  | ErrorEvent
  | StatusEvent;

export type ServerEventType = ServerEvent["type"];
export type ServerEventOf<T extends ServerEventType> = Extract<ServerEvent, { type: T }>;

// ---------------------------------------------------------------- helpers

/** Matches citation tags in assistant text; group 1 is the citation id. Mirrors trust/guardrails.py CITE. */
export const CITATION_TAG = /\[([\w.\-]+:[\w.\-]+)\]/g;

export type MaskedField = "EMAIL" | "UPI" | "PAN" | "AADHAAR" | "PHONE" | "ACCOUNT";

/** Matches masked identifiers like "[PAN_1]"; group 1 is the field, group 2 the index. Mirrors trust/pii.py. */
export const MASK_TAG = /\[(EMAIL|UPI|PAN|AADHAAR|PHONE|ACCOUNT)_(\d+)\]/g;

/** Max length of one recording, in seconds. */
export const MAX_RECORDING_SECONDS = 30;

/** Parses a JSON text frame. Returns null for anything that is not a known server event. */
export function parseServerEvent(raw: string): ServerEvent | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null || !("type" in data)) return null;
  return SERVER_EVENT_TYPES.has((data as { type: string }).type) ? (data as ServerEvent) : null;
}

const SERVER_EVENT_TYPES: ReadonlySet<string> = new Set<ServerEventType>([
  "session",
  "consent_required",
  "consent",
  "card",
  "user",
  "assistant",
  "done",
  "handoff",
  "error",
  "status",
]);
