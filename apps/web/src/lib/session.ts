import type { ConsentRequiredEvent, ServerEvent } from "@sahaj/contracts";
import { player } from "@/lib/audio/player";
import { MicUnavailable, Recorder } from "@/lib/audio/recorder";
import { VoiceSocket } from "@/lib/socket";
import { canTalk, initialSession, nextId, pushItem, useSession } from "@/store/session";

/**
 * Side effects of a conversation: the socket, the mic and the speaker. Components read `useSession` and call
 * these functions; nothing else touches the socket.
 */

const set = useSession.setState;
const get = useSession.getState;

/** Give up on a turn that gets no reply (the server normally answers within a few seconds). */
const TURN_TIMEOUT_MS = 60_000;
let turnTimer: ReturnType<typeof setTimeout> | null = null;

function setThinking() {
  set({ turn: "thinking" });
  if (turnTimer) clearTimeout(turnTimer);
  turnTimer = setTimeout(() => {
    if (get().turn !== "thinking") return;
    player.discard();
    set({ turn: "idle" });
    pushItem({ kind: "error", text: "Sahaj took too long to answer. Please try again." });
  }, TURN_TIMEOUT_MS);
}

function settle(turn: "idle" | "speaking" = "idle") {
  if (turnTimer) clearTimeout(turnTimer);
  turnTimer = null;
  set({ turn });
}

const socket = new VoiceSocket({
  onStatus(connection, { reconnected }) {
    set({ connection });
    if (connection !== "open" && get().turn !== "idle") {
      player.discard();
      void recorder.cancel();
      settle();
    }
    if (reconnected) {
      // A new socket is a new server session: it forgot the conversation and will ask for consent again.
      set({ consent: initialSession.consent, consentPrompt: null, handoff: null, sessionId: null });
      pushItem({ kind: "system", text: "Reconnected. The conversation was reset, so earlier messages are not remembered." });
    }
  },
  onAudio(chunk) {
    player.push(chunk);
  },
  onEvent: handleEvent,
});

function handleEvent(e: ServerEvent) {
  switch (e.type) {
    case "session":
      set({ sessionId: e.id });
      break;
    case "consent_required":
      set({ consentPrompt: e });
      // Audio sent without consent gets only this reply (no `done`), so the turn ends here.
      if (e.purpose === "conversation" && get().turn === "thinking") settle();
      break;
    case "consent":
      set((s) => ({ consent: { ...s.consent, [e.purpose]: e.status } }));
      pushItem({
        kind: "system",
        text:
          e.purpose === "conversation"
            ? e.status === "granted" ? "Consent given" : "Consent withdrawn. The conversation was cleared."
            : e.status === "granted" ? "Permission to use your details given" : "Permission to use your details withdrawn",
      });
      break;
    case "user":
      pushItem({ id: nextId(), kind: "user", text: e.text });
      break;
    case "card":
      pushItem({ id: nextId(), kind: "card", card: e.card, traceId: e.trace_id });
      break;
    case "assistant":
      pushItem({
        id: nextId(), kind: "assistant", agent: e.agent, text: e.text, citations: e.citations,
        traceId: e.trace_id, audioUrl: null,
      });
      break;
    case "done":
      void playReply();
      break;
    case "handoff":
      player.discard();
      settle();
      set({ handoff: { reference: e.reference, reason: e.reason ?? get().handoff?.reason } });
      break;
    case "error":
      player.discard();
      settle();
      pushItem({ kind: "error", text: e.message });
      break;
  }
}

async function playReply() {
  const items = get().timeline;
  const last = [...items].reverse().find((i) => i.kind === "assistant");
  settle("speaking");
  const url = await player.playCollected(() => {
    if (get().turn === "speaking") set({ turn: "idle" });
  });
  if (!url) return settle(); // text-only language or no audio
  if (last) {
    set((s) => ({
      timeline: s.timeline.map((i) => (i.id === last.id && i.kind === "assistant" ? { ...i, audioUrl: url } : i)),
    }));
  }
}

// ---------------------------------------------------------------- public API

const recorder = new Recorder();

export function connect() {
  socket.connect();
  const wake = () => document.visibilityState === "visible" && socket.wake();
  // iOS closes sockets when the app is backgrounded or the phone locks; reconnect on return.
  document.addEventListener("visibilitychange", wake);
  window.addEventListener("online", wake);
  window.addEventListener("pageshow", wake);
}

/** Call from pointerdown / keydown. */
export async function startTalking() {
  player.stop(); // barge in on a reply that is still playing
  player.unlock(); // must happen synchronously inside the gesture (iOS)
  const s = get();
  if (!canTalk(s) && s.turn !== "speaking") return;
  set({ turn: "starting", micError: null });
  try {
    await recorder.start(() => void stopTalking());
    // released before the mic opened: stopTalking already ran, so end the recording now
    if (get().turn !== "starting") return void recorder.cancel();
    set({ turn: "recording", recordingSince: Date.now() });
  } catch (err) {
    set({ turn: "idle", micError: err instanceof MicUnavailable ? err.reason : "unknown" });
  }
}

/** Call from pointerup / keyup, and when the 30 s limit is reached. */
export async function stopTalking() {
  const turn = get().turn;
  if (turn === "starting") return set({ turn: "idle" }); // tap too short
  if (turn !== "recording") return;
  const startedAt = get().recordingSince ?? Date.now();
  set({ recordingSince: null });
  const recording = await recorder.stop();
  if (!recording || Date.now() - startedAt < 400) {
    set({ turn: "idle" });
    return pushItem({ kind: "error", text: "Hold the button while you speak." });
  }
  if (!socket.sendAudio(recording)) {
    set({ turn: "idle" });
    return pushItem({ kind: "error", text: "Not connected. Please try again in a moment." });
  }
  setThinking();
}

export async function cancelTalking() {
  if (get().turn !== "recording" && get().turn !== "starting") return;
  await recorder.cancel();
  set({ turn: "idle", recordingSince: null });
}

let lastConversationPrompt: ConsentRequiredEvent | null = null;

export function answerConsent(granted: boolean) {
  const prompt = get().consentPrompt;
  if (!prompt) return;
  if (prompt.purpose === "conversation") lastConversationPrompt = prompt;
  set({ consentPrompt: null });
  socket.send({ type: "consent", purpose: prompt.purpose, granted });
  // Granting needs_analysis makes the server answer the question that triggered it.
  if (granted && prompt.purpose === "needs_analysis") setThinking();
}

/** Shows the conversation consent again after the person declined it. */
export function reviewConsent() {
  if (lastConversationPrompt && get().consent.conversation !== "granted") set({ consentPrompt: lastConversationPrompt });
}

export function withdrawConsent(purpose: "conversation" | "needs_analysis") {
  socket.send({ type: "consent", purpose, granted: false });
}

export function requestHuman() {
  player.stop();
  socket.send({ type: "handoff" });
}

export function replay(url: string) {
  const turn = get().turn;
  if (turn !== "idle" && turn !== "speaking") return;
  set({ turn: "speaking" });
  void player.replay(url, () => get().turn === "speaking" && set({ turn: "idle" }));
}

export function stopSpeaking() {
  player.stop();
}
