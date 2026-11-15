/**
 * Voice WebSocket protocol (`/ws/voice`). Source of truth: docs/voice-api.md.
 * Keep in sync with apps/api/routers/voice.py and the orchestrator events it emits.
 */

import type { User } from "./http";

/** "memory" belongs to the signed-in person (it applies across conversations); the others to one conversation. */
export type ConsentPurpose = "conversation" | "needs_analysis" | "memory";
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

/** A typed message. It takes the same path as speech; the reply is spoken only when `speak` is true. */
export interface TextMessage {
  type: "text";
  /** 1 to 2000 characters. */
  text: string;
  /** BCP-47 tag such as "hi-IN". Defaults to the user's profile language. */
  language?: string;
  speak?: boolean;
}

export type ClientMessage = ConsentMessage | HandoffRequest | TextMessage;

// ---------- Server -> client (JSON text frames; MP3 chunks arrive as binary frames) ----------

export interface SessionEvent {
  type: "session";
  id: string;
  user: User;
  /** True when Sahaj is using what it remembers about this person in this conversation. */
  memory: boolean;
}

/** Close code when the access token is missing, invalid or expired: refresh it (POST /auth/refresh) and reconnect. */
export const WS_UNAUTHORIZED = 4401;

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

export type Stage = "transcribing" | "thinking" | "checking" | "speaking";

/** Progress through a turn. Carries no content: the reply arrives whole, after the guardrails have passed it. */
export interface StatusEvent {
  type: "status";
  stage: Stage;
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
  | StatusEvent
  | CardEvent
  | UserEvent
  | AssistantEvent
  | DoneEvent
  | HandoffEvent
  | ErrorEvent;

export type ServerEventType = ServerEvent["type"];
