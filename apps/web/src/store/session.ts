import type {
  AgentName,
  Card,
  Citation,
  ConsentPurpose,
  ConsentRequiredEvent,
  HandoffReason,
} from "@sahaj/contracts";
import { create } from "zustand";
import type { MicError } from "@/lib/audio/recorder";
import type { ConnectionStatus } from "@/lib/socket";

/** Where the push-to-talk turn is. Drives the talk button. */
export type TurnState = "idle" | "starting" | "recording" | "thinking" | "speaking";

export type ConsentState = "unknown" | "granted" | "revoked";

export type TimelineItem =
  | { id: string; kind: "user"; text: string }
  | {
      id: string;
      kind: "assistant";
      agent: AgentName;
      text: string;
      citations: Citation[];
      traceId: string;
      /** Spoken reply, for the replay button. null = text only (no voice for the language, or not played yet). */
      audioUrl: string | null;
    }
  | { id: string; kind: "card"; card: Card; traceId: string }
  | { id: string; kind: "system"; text: string }
  | { id: string; kind: "error"; text: string };

export interface SessionState {
  connection: ConnectionStatus;
  sessionId: string | null;
  consent: Record<ConsentPurpose, ConsentState>;
  /** A consent request waiting for the person's answer (show it verbatim). */
  consentPrompt: ConsentRequiredEvent | null;
  turn: TurnState;
  /** Recording start time (ms), for the 0:30 timer. */
  recordingSince: number | null;
  micError: MicError | null;
  handoff: { reference: string; reason?: HandoffReason } | null;
  timeline: TimelineItem[];
}

export const initialSession: SessionState = {
  connection: "connecting",
  sessionId: null,
  consent: { conversation: "unknown", needs_analysis: "unknown" },
  consentPrompt: null,
  turn: "idle",
  recordingSince: null,
  micError: null,
  handoff: null,
  timeline: [],
};

export const useSession = create<SessionState>(() => initialSession);

let counter = 0;
export const nextId = () => `t${Date.now().toString(36)}${(counter++).toString(36)}`;

export function pushItem(item: TimelineItem | Omit<Extract<TimelineItem, { kind: "system" | "error" }>, "id">) {
  const withId = ("id" in item ? item : { ...item, id: nextId() }) as TimelineItem;
  useSession.setState((s) => ({ timeline: [...s.timeline, withId] }));
}

/** The person may start a new recording. */
export const canTalk = (s: SessionState) =>
  s.connection === "open" && s.consent.conversation === "granted" && !s.handoff && !s.consentPrompt && s.turn === "idle";
