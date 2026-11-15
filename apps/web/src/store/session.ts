import type {
  AgentName,
  Card,
  CaseView,
  Citation,
  ConsentPurpose,
  ConsentRequiredEvent,
  FinancialWorkflowCard,
  HandoffReason,
  ReplyKind,
  Stage,
  User,
  Verification,
} from "@sahaj/contracts";
import { create } from "zustand";
import type { MicError } from "@/lib/audio/recorder";
import type { StringKey } from "@/lib/i18n";
import type { ConnectionStatus } from "@/lib/socket";

/** Where the push-to-talk turn is. Drives the dock. */
export type TurnState = "idle" | "starting" | "recording" | "sending" | "thinking" | "speaking";

export interface ConsentInfo {
  state: "unknown" | "granted" | "revoked";
  version?: string;
  at?: number;
}

/** Cards the app can render. The financial workflow has no UI yet; its reply text explains the next step. */
export type ShownCard = Exclude<Card, FinancialWorkflowCard>;

export type TimelineItem =
  | { id: string; kind: "user"; text: string }
  | {
      id: string;
      kind: "assistant";
      agent: AgentName;
      text: string;
      citations: Citation[];
      traceId: string;
      replyKind: ReplyKind;
      fallback: boolean;
      /** Spoken reply for replay. null = not spoken (text-only language, or no audio). */
      audioUrl: string | null;
      audioSeconds: number | null;
      textOnly: boolean;
      /** How the reply was checked (trust badge) and follow-ups to offer as chips. */
      verification: Verification | null;
      suggestions: string[];
      feedback: "up" | "down" | null;
    }
  /** A message from the person (executive) handling the conversation. */
  | { id: string; kind: "agent"; name: string; text: string }
  | { id: string; kind: "card"; card: ShownCard; traceId: string }
  /** Inline consent request (needs analysis is asked in the conversation, not in a sheet). */
  | { id: string; kind: "consent"; prompt: ConsentRequiredEvent; answered: boolean | null }
  | { id: string; kind: "system"; icon: string; text: StringKey; tone?: "success" | "muted"; vars?: Record<string, string | number> }
  | { id: string; kind: "reset" };

/** A person from the team is (or will be) handling the conversation. Messages go to them, not the AI. */
export interface HandoffState {
  reference: string;
  reason?: HandoffReason;
  case: CaseView | null;
  /** Set once an executive has joined. */
  agentName: string | null;
  /** The case was closed: back to Sahaj. Kept so the card can say so. */
  closed?: "resolved" | "cancelled";
}

export interface SessionState {
  connection: ConnectionStatus;
  sessionId: string | null;
  user: User | null;
  consent: Record<ConsentPurpose, ConsentInfo>;
  /** The conversation consent sheet (needs_analysis is shown inline instead). */
  consentPrompt: ConsentRequiredEvent | null;
  /** The person declined the conversation consent. */
  declined: boolean;
  turn: TurnState;
  /** The reply's text has arrived for this turn (its audio may still be on the way). */
  replied: boolean;
  /** Latest server status step while thinking. */
  status: Stage | null;
  statusHistory: Stage[];
  recordingSince: number | null;
  /** Mic input level 0..1 while recording, for the bars. */
  level: number;
  /** Speaking progress, seconds. */
  speaking: { elapsed: number; duration: number } | null;
  muted: boolean;
  micError: MicError | null;
  /** Transient message in the dock ("I didn't catch that…"). */
  /** A string key, or a message the server wrote for the person. */
  dockError: StringKey | string | null;
  /** The last reply had no audio because the language is text only. */
  lastTextOnly: boolean;
  /** Needs-analysis progress from the server. */
  progress: { step: number; total: number } | null;
  handoff: HandoffState | null;
  /** Monthly allowance: warned once near the limit; when used up, nothing more is processed until it resets. */
  budget: { warned: boolean; exceededUntil: string | null };
  timeline: TimelineItem[];
}

export const initialSession: SessionState = {
  connection: "connecting",
  sessionId: null,
  user: null,
  consent: {
    conversation: { state: "unknown" }, needs_analysis: { state: "unknown" }, memory: { state: "unknown" },
    documents: { state: "unknown" }, document_analysis: { state: "unknown" }, conversation_records: { state: "unknown" },
    video_kyc: { state: "unknown" }, financial_application: { state: "unknown" }, credit_bureau: { state: "unknown" },
    financial_profile: { state: "unknown" },
  },
  consentPrompt: null,
  declined: false,
  turn: "idle",
  replied: false,
  status: null,
  statusHistory: [],
  recordingSince: null,
  level: 0,
  speaking: null,
  muted: false,
  micError: null,
  dockError: null,
  lastTextOnly: false,
  progress: null,
  handoff: null,
  budget: { warned: false, exceededUntil: null },
  timeline: [],
};

export const useSession = create<SessionState>(() => initialSession);

let counter = 0;
export const nextId = () => `t${Date.now().toString(36)}${(counter++).toString(36)}`;

type NewItem = TimelineItem extends infer T ? (T extends { id: string } ? Omit<T, "id"> : never) : never;

export function pushItem(item: NewItem): string {
  const id = nextId();
  useSession.setState((s) => ({ timeline: [...s.timeline, { ...item, id } as TimelineItem] }));
  return id;
}

export function updateItem(id: string, patch: Partial<TimelineItem>) {
  useSession.setState((s) => ({
    timeline: s.timeline.map((i) => (i.id === id ? ({ ...i, ...patch } as TimelineItem) : i)),
  }));
}

/** A person is handling the conversation right now (talking goes to them). */
export const withPerson = (s: SessionState) => !!s.handoff && !s.handoff.closed;

/** The person may start a new recording. While a person handles the case, recordings go to them. */
export const canTalk = (s: SessionState) =>
  s.connection === "open" &&
  s.consent.conversation.state === "granted" &&
  !s.budget.exceededUntil &&
  !s.consentPrompt &&
  !s.timeline.some((i) => i.kind === "consent" && i.answered === null) &&
  (s.turn === "idle" || s.turn === "speaking");

/** The open case is a video KYC appointment (requested, or booked by the team). */
export const kycCase = (s: SessionState) =>
  withPerson(s) && (s.handoff?.case?.kind === "video_kyc" || s.handoff?.reason === "video_kyc") ? s.handoff : null;

/** The most recent card, for the desktop side panel. */
export const latestCard = (s: SessionState) =>
  [...s.timeline].reverse().find((i): i is Extract<TimelineItem, { kind: "card" }> => i.kind === "card") ?? null;

/** The most recent spoken reply, for the dock's replay button. */
export const lastSpoken = (s: SessionState) =>
  [...s.timeline].reverse().find((i): i is Extract<TimelineItem, { kind: "assistant" }> => i.kind === "assistant" && !!i.audioUrl) ?? null;
