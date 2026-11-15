/**
 * Voice WebSocket protocol (`/ws/voice`).
 *
 * Source of truth is the backend, not the prose docs:
 *   events  apps/api/orchestrator/session.py (desk events: apps/api/desk, routers/desk.py)
 *   cards   apps/api/advisory/flow.py (profile_summary, recommendation)
 *           apps/api/advisory/compare.py (comparison)
 *           apps/api/loan/flow.py + loan/calc.py (loan_calculation)
 *   consent apps/api/trust/consent.py
 * Update this file in the same change as any of those.
 */

import type { User } from "./http";

/** "memory" belongs to the signed-in person (it applies across conversations); the others to one conversation. */
export type ConsentPurpose =
  | "conversation" | "needs_analysis" | "memory" | "documents" | "document_analysis" | "conversation_records"
  | "video_kyc" | "financial_application" | "credit_bureau" | "financial_profile";
/** "advice" is the needs-analysis / recommendation flow. */
export type AgentName = "insurance" | "loan" | "general" | "advice";
export type HandoffReason = "user_requested" | "guardrail_failures" | "stuck_in_questions" | "low_confidence" | "complaint" | "distress" | "video_kyc" | "callback";

export type InsuranceGoal = "health" | "term" | "whole_life";

/** The open desk case: while it exists, messages go to the executive, not the AI. */
export interface CaseView {
  id: string;
  reference: string;
  kind: "handoff" | "complaint" | "video_kyc" | "callback";
  status: "waiting" | "with_executive";
  priority: "urgent" | "high" | "normal";
  /** Video KYC: the booked appointment (ISO time with timezone) and its HTTPS link, once an executive has set them. */
  scheduled_for?: string | null;
  meeting_url?: string | null;
}

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
export type ReplyKind = "answer" | "ask" | "confirm" | "recommendation" | "compare" | "calc" | "command";

// ---------------------------------------------------------------- client -> server
// Audio: send one complete recording (max 30 s; WebM or Safari's MP4, detected server-side) as a binary frame,
// only after done/error/handoff.

export interface ConsentMessage {
  type: "consent";
  purpose: ConsentPurpose;
  granted: boolean;
  /** The `version` of the text that was shown. Without it the grant is recorded as unconfirmed; a stale one is refused. */
  version?: string;
}

export interface HandoffRequest {
  type: "handoff";
  /** Default: a person, for anything. video_kyc needs the video_kyc consent. */
  reason?: "video_kyc" | "callback" | "complaint";
  note?: string;
}

export interface HandoffCancel {
  type: "handoff_cancel";
}

/** A typed message. It takes the same path as speech; the reply is spoken only when `speak` is true. */
export interface TextMessage {
  type: "text";
  /** 1 to 2000 characters. */
  text: string;
  /** BCP-47 tag such as "hi-IN". Defaults to the user's profile language. */
  language?: string;
  speak?: boolean;
}

export type ClientMessage = ConsentMessage | HandoffRequest | HandoffCancel | TextMessage;

/** Stream endpoint controls. Audio arrives in binary WebSocket frames until audio_end or audio_cancel. */
export type VoiceStreamControl = { type: "audio_end" } | { type: "audio_cancel" };

// ---------------------------------------------------------------- server -> client
// Binary frames are MP3 chunks of the spoken answer; join them in order and play on `done`.

export interface SessionEvent {
  type: "session";
  id: string;
  user: User;
  /** True when Sahaj is using what it remembers about this person in this conversation. */
  memory: boolean;
  /** A person is already handling this customer: carry on with them. */
  case: CaseView | null;
  /** True when this conversation was restored from a saved one rather than started fresh. */
  resumed: boolean;
  /** Which consents the account already has (they carry over between conversations and devices). */
  consents: Partial<Record<ConsentPurpose | "video_kyc", boolean>>;
}

/** Close code when the access token is missing, invalid or expired: refresh it (POST /auth/refresh) and reconnect. */
export const WS_UNAUTHORIZED = 4401;

export interface ConsentRequiredEvent {
  type: "consent_required";
  purpose: ConsentPurpose;
  title: string;
  version: string;
  /** Show verbatim with accept and decline actions. */
  text: string;
  required: boolean;
  requires: ConsentPurpose | null;
  /** What withdrawing does, for a confirmation. */
  withdrawal: string;
}

export interface ConsentStatusEvent {
  type: "consent";
  purpose: ConsentPurpose;
  status: "granted" | "revoked";
}

/**
 * Where a turn is, in order: transcribing → thinking → (searching | comparing | calculating) → checking → speaking.
 * searching/comparing/calculating come from the graph node doing the work, for "Finding the right documents…" hints.
 * speech_unavailable: the spoken reply could not be produced; the written reply is complete.
 * Clients should ignore stages they don't know.
 */
export type Stage =
  | "transcribing" | "thinking" | "searching" | "comparing" | "calculating" | "checking" | "speaking"
  | "speech_unavailable" | "waiting_for_executive";

/** Progress through a turn. Carries no content: the reply arrives whole, after the guardrails have passed it. */
export interface StatusEvent {
  type: "status";
  stage: Stage;
}

/** The person has used BUDGET_WARN_AT (80%) of this month's allowance. Sent once per conversation. */
export interface UsageWarningEvent {
  type: "usage_warning";
  spent_usd: number;
  budget_usd: number;
  percent_used: number;
}

/** The allowance is used up: the message was not processed. */
export interface BudgetExceededEvent {
  type: "budget_exceeded";
  spent_usd: number;
  budget_usd: number;
  resets_at: string;
}

/** A new offer in the person's inbox (only with the marketing consent). */
export interface InboxEvent { type: "inbox"; item: { title: string; body: string; cta_label: string | null; has_image: boolean } }

export interface UserEvent {
  type: "user";
  /** Transcript with identifiers already masked, e.g. "[PAN_1]". See MASK_TAG. */
  text: string;
}

/** The reply split into statements, each with the sources behind it. Built from the verified `text`, nothing added. */
export interface StructuredReply {
  kind: ReplyKind;
  /** The first statement: a one-line headline. */
  summary: string;
  points: { text: string; sources: string[] }[];
  /** Every source used, once; `points[].sources` refer to these ids. Display details are in `citations`. */
  sources: { id: string; text: string }[];
  /** Fixed text such as disclosures, kept apart from the answer. */
  notes: string[];
}

/** How a reply was checked, for a trust badge. verified: every statement tied to a source and fact-checked.
 *  engine: built from the recommendation/calculation engine's own figures. checked: screened by the guardrails, nothing to
 *  cite. blocked: the draft failed the checks and a safe reply was shown instead. */
export interface Verification {
  level: "verified" | "engine" | "checked" | "blocked";
  sources: number;
  from_cache: boolean;
  checks: ("guardrails" | "fact_check")[];
}

export interface AssistantEvent {
  type: "assistant";
  agent: AgentName;
  /** The whole reply, source tags included ("[health-lotus-care:3.2]", see CITATION_TAG). `structured` splits it into points. */
  text: string;
  citations: Citation[];
  structured: StructuredReply;
  verification: Verification;
  /** Up to three follow-up questions to show as chips; send one back as a `text` message. Empty while Sahaj is asking something. */
  suggestions: string[];
  trace_id: string;
  /** "ask" = Sahaj is asking a question (clarifying, or the next needs-analysis question). */
  kind: ReplyKind;
  /** True when the checks blocked the answer and this is the safe "I can't confirm that…" reply. */
  fallback: boolean;
  /** Needs analysis only: which question this is, for "Understanding your needs · 4 of 9". */
  progress?: { step: number; total: number };
}

export interface DoneEvent {
  type: "done";
}

export interface HandoffEvent {
  type: "handoff";
  reference: string;
  reason: HandoffReason;
  case: CaseView;
}

export interface AgentJoinedEvent { type: "agent_joined"; case_id: string; agent: { name: string } }
export interface AgentLeftEvent { type: "agent_left"; case_id: string }
export interface AgentMessageEvent { type: "agent_message"; case_id: string; text: string; agent: { name: string }; at: string }
export interface VideoKycScheduledEvent { type: "video_kyc_scheduled"; case_id: string; scheduled_for: string; meeting_url: string | null }
/** The person finished (resolved) or the customer withdrew (cancelled): the AI answers again. */
export interface HandoffClosedEvent { type: "handoff_closed"; case_id?: string; status: "resolved" | "cancelled"; outcome?: string; message?: string | null }

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

/** Arrives with kind "ask": the user must review the provider and consent before anything is submitted. */
export interface FinancialWorkflowCard {
  type: "financial_workflow";
  action: "insurance_purchase" | "loan_application" | "credit_check";
  providers: string[];
  endpoints: string[];
  consent: { purpose: ConsentPurpose; title: string; version: string; text: string; [key: string]: unknown };
  requires_user_confirmation: true;
}

export type Card = ProfileSummaryCard | RecommendationCard | ComparisonCard | LoanCalculationCard | FinancialWorkflowCard;
export type CardType = Card["type"];

/** The turn kind that produced the card. Prefer `card.type` for rendering. */
export type TurnKind = "confirm" | "recommendation" | "compare" | "calc" | "ask";

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
  | StatusEvent
  | InboxEvent
  | UsageWarningEvent
  | BudgetExceededEvent
  | CardEvent
  | UserEvent
  | AssistantEvent
  | DoneEvent
  | HandoffEvent
  | AgentJoinedEvent
  | AgentLeftEvent
  | AgentMessageEvent
  | VideoKycScheduledEvent
  | HandoffClosedEvent
  | ErrorEvent;

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
  "status",
  "usage_warning",
  "budget_exceeded",
  "card",
  "user",
  "assistant",
  "done",
  "handoff",
  "agent_joined",
  "agent_left",
  "agent_message",
  "video_kyc_scheduled",
  "handoff_closed",
  "error",
]);
