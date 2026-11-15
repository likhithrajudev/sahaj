import type {
  AgentName,
  Card,
  Citation,
  ConsentPurpose,
  ConsentRequiredEvent,
  HandoffReason,
  ReplyKind,
  StatusStep,
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
    }
  | { id: string; kind: "card"; card: Card; traceId: string }
  /** Inline consent request (needs analysis is asked in the conversation, not in a sheet). */
  | { id: string; kind: "consent"; prompt: ConsentRequiredEvent; answered: boolean | null }
  | { id: string; kind: "system"; icon: string; text: StringKey; tone?: "success" | "muted" }
  | { id: string; kind: "reset" };

export interface SessionState {
  connection: ConnectionStatus;
  sessionId: string | null;
  consent: Record<ConsentPurpose, ConsentInfo>;
  /** The conversation consent sheet (needs_analysis is shown inline instead). */
  consentPrompt: ConsentRequiredEvent | null;
  /** The person declined the conversation consent. */
  declined: boolean;
  turn: TurnState;
  /** Latest server status step while thinking. */
  status: StatusStep | null;
  statusHistory: StatusStep[];
  recordingSince: number | null;
  /** Mic input level 0..1 while recording, for the bars. */
  level: number;
  /** Speaking progress, seconds. */
  speaking: { elapsed: number; duration: number } | null;
  muted: boolean;
  micError: MicError | null;
  /** Transient message in the dock ("I didn't catch that…"). */
  dockError: StringKey | null;
  /** The last reply had no audio because the language is text only. */
  lastTextOnly: boolean;
  /** Needs-analysis progress from the server. */
  progress: { step: number; total: number } | null;
  handoff: { reference: string; reason?: HandoffReason } | null;
  timeline: TimelineItem[];
}

export const initialSession: SessionState = {
  connection: "connecting",
  sessionId: null,
  consent: { conversation: { state: "unknown" }, needs_analysis: { state: "unknown" } },
  consentPrompt: null,
  declined: false,
  turn: "idle",
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

/** The person may start a new recording. */
export const canTalk = (s: SessionState) =>
  s.connection === "open" &&
  s.consent.conversation.state === "granted" &&
  !s.handoff &&
  !s.consentPrompt &&
  !s.timeline.some((i) => i.kind === "consent" && i.answered === null) &&
  (s.turn === "idle" || s.turn === "speaking");

/** The most recent card, for the desktop side panel. */
export const latestCard = (s: SessionState) =>
  [...s.timeline].reverse().find((i): i is Extract<TimelineItem, { kind: "card" }> => i.kind === "card") ?? null;

/** The most recent spoken reply, for the dock's replay button. */
export const lastSpoken = (s: SessionState) =>
  [...s.timeline].reverse().find((i): i is Extract<TimelineItem, { kind: "assistant" }> => i.kind === "assistant" && !!i.audioUrl) ?? null;
