/**
 * Voice WebSocket protocol (`/ws/voice`). Source of truth: docs/voice-api.md.
 * Keep in sync with apps/api/routers/voice.py and the orchestrator events it emits.
 */

export type ConsentPurpose = "conversation" | "needs_analysis";
export type AgentName = "insurance" | "loan" | "general";
export type HandoffReason = "user_requested" | "guardrail_failures" | "stuck_in_questions";

export interface Citation {
  /** Source tag as it appears in the answer text, e.g. "policy:3.2". */
  id: string;
  text: string;
}

// ---------- Client -> server (JSON text frames; audio is sent as a binary frame) ----------

export interface ConsentMessage {
  type: "consent";
  purpose: ConsentPurpose;
  granted: boolean;
}

export interface HandoffRequest {
  type: "handoff";
}

export type ClientMessage = ConsentMessage | HandoffRequest;

// ---------- Server -> client (JSON text frames; MP3 chunks arrive as binary frames) ----------

export interface SessionEvent {
  type: "session";
  id: string;
}

export interface ConsentRequiredEvent {
  type: "consent_required";
  purpose: ConsentPurpose;
  version: string;
  /** Show verbatim with accept and decline buttons. */
  text: string;
}

export interface ConsentStatusEvent {
  type: "consent";
  purpose: ConsentPurpose;
  status: "granted" | "revoked";
}

export interface UserEvent {
  type: "user";
  /** Masked transcript (e.g. "[PAN_1]"). */
  text: string;
}

export interface AssistantEvent {
  type: "assistant";
  agent: AgentName;
  text: string;
  citations: Citation[];
  trace_id: string;
}

export interface DoneEvent {
  type: "done";
}

export interface HandoffEvent {
  type: "handoff";
  reference: string;
  reason: HandoffReason;
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

// ---------- Cards (structured UI, sent just before the matching assistant message) ----------

export interface ProfileSummaryCard {
  details: string[];
}

export interface RecommendedPlan {
  name: string;
  insurer: string;
  cover: number;
  annual_premium: number;
  highlights: string[];
  reasons: string[];
  criteria: Record<string, unknown>;
}

export interface RecommendationCard {
  suggested_cover: { amount: number; basis: string; note: string };
  plans: RecommendedPlan[];
  disclosures: string[];
  sample_data: boolean;
  indicative_premiums: boolean;
}

export interface ComparisonCard {
  plans: { name: string; rows: [label: string, value: string][] }[];
}

export interface CalcCard {
  kind: "emi" | "prepayment";
  inputs: Record<string, unknown>;
  result: Record<string, unknown>;
}

export interface CardPayloads {
  profile_summary: ProfileSummaryCard;
  recommendation: RecommendationCard;
  comparison: ComparisonCard;
  calc: CalcCard;
}

export type CardKind = keyof CardPayloads;

export type CardEvent = {
  [K in CardKind]: { type: "card"; kind: K; card: CardPayloads[K]; trace_id: string };
}[CardKind];

export type ServerEvent =
  | SessionEvent
  | ConsentRequiredEvent
  | ConsentStatusEvent
  | CardEvent
  | UserEvent
  | AssistantEvent
  | DoneEvent
  | HandoffEvent
  | ErrorEvent;

export type ServerEventType = ServerEvent["type"];
