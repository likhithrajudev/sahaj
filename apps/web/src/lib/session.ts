import type { ConsentPurpose, ConsentRequiredEvent, ServerEvent } from "@sahaj/contracts";
import { audioDuration, player } from "@/lib/audio/player";
import { MicUnavailable, Recorder } from "@/lib/audio/recorder";
import type { StringKey } from "@/lib/i18n";
import { VoiceSocket } from "@/lib/socket";
import { canTalk, initialSession, pushItem, updateItem, useSession } from "@/store/session";
import { openSheet, useUi } from "@/store/ui";

/**
 * Side effects of a conversation: the socket, the mic and the speaker. Components read `useSession` and call
 * these functions; nothing else touches the socket.
 */

const set = useSession.setState;
const get = useSession.getState;

/** Give up on a turn that gets no reply (the server normally answers within a few seconds). */
const TURN_TIMEOUT_MS = 60_000;
let turnTimer: ReturnType<typeof setTimeout> | null = null;
let dockErrorTimer: ReturnType<typeof setTimeout> | null = null;
const lastPrompt: Partial<Record<ConsentPurpose, ConsentRequiredEvent>> = {};

function waitForReply(turn: "sending" | "thinking") {
  set({ turn });
  if (turnTimer) clearTimeout(turnTimer);
  turnTimer = setTimeout(() => {
    if (get().turn !== "sending" && get().turn !== "thinking") return;
    player.discard();
    settle();
    showDockError("tooLong");
  }, TURN_TIMEOUT_MS);
}

function settle(turn: "idle" | "speaking" = "idle") {
  if (turnTimer) clearTimeout(turnTimer);
  turnTimer = null;
  set({ turn, status: null, statusHistory: turn === "idle" ? [] : get().statusHistory, level: 0 });
}

function showDockError(message: StringKey) {
  set({ dockError: message });
  if (dockErrorTimer) clearTimeout(dockErrorTimer);
  dockErrorTimer = setTimeout(() => set({ dockError: null }), 8000);
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
      set({
        consent: initialSession.consent, consentPrompt: null, handoff: null, sessionId: null, progress: null,
        declined: false,
        timeline: get().timeline.map((i) => (i.kind === "consent" && i.answered === null ? { ...i, answered: false } : i)),
      });
      if (get().timeline.length) pushItem({ kind: "reset" });
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
      lastPrompt[e.purpose] = e;
      if (e.purpose === "conversation") {
        set({ consentPrompt: e });
        // Audio sent without consent gets only this reply (no `done`), so the turn ends here.
        if (get().turn === "thinking" || get().turn === "sending") settle();
      } else {
        // The needs-analysis permission is asked inside the conversation, as a card.
        pushItem({ kind: "consent", prompt: e, answered: null });
      }
      break;

    case "consent": {
      const prompt = lastPrompt[e.purpose];
      set((s) => ({
        consent: { ...s.consent, [e.purpose]: { state: e.status, version: prompt?.version, at: Date.now() } },
        declined: e.purpose === "conversation" && e.status === "revoked" ? true : s.declined,
      }));
      if (e.purpose === "conversation" && e.status === "granted") set({ declined: false });
      if (e.purpose === "conversation") {
        pushItem(e.status === "granted"
          ? { kind: "system", icon: "verified_user", text: "consentGranted", tone: "success" }
          : { kind: "system", icon: "remove_moderator", text: "consentWithdrawn" });
      } else {
        pushItem(e.status === "granted"
          ? { kind: "system", icon: "verified_user", text: "detailsGranted", tone: "success" }
          : { kind: "system", icon: "remove_moderator", text: "detailsWithdrawn" });
        if (e.status === "revoked") set({ progress: null });
      }
      break;
    }

    case "user":
      set({ dockError: null });
      pushItem({ kind: "user", text: e.text });
      if (get().turn === "sending") waitForReply("thinking"); // transcribed: now Sahaj is working on it
      break;

    case "status":
      if (e.stage === "speaking" || e.stage === "speech_unavailable" || e.stage === "waiting_for_executive") break;
      set((s) => ({
        status: e.stage,
        statusHistory: s.statusHistory.includes(e.stage) ? s.statusHistory : [...s.statusHistory, e.stage],
        turn: s.turn === "sending" && e.stage !== "transcribing" ? "thinking" : s.turn,
      }));
      break;

    case "card":
      pushItem({ kind: "card", card: e.card, traceId: e.trace_id });
      if (useUi.getState().panelItemId) useUi.setState({ panelItemId: null }); // panel follows the newest card
      break;

    case "assistant": {
      pushItem({
        kind: "assistant", agent: e.agent, text: e.text, citations: e.citations, traceId: e.trace_id,
        replyKind: e.kind ?? "answer", fallback: !!e.fallback, audioUrl: null, audioSeconds: null, textOnly: false,
      });
      // The server asks for the needs-analysis permission just before the message that explains why;
      // show the message first, then the permission card under it.
      const items = get().timeline;
      const consentIdx = items.length - 2;
      if (items[consentIdx]?.kind === "consent" && (items[consentIdx] as { answered: boolean | null }).answered === null) {
        const reordered = [...items];
        [reordered[consentIdx], reordered[consentIdx + 1]] = [reordered[consentIdx + 1], reordered[consentIdx]];
        set({ timeline: reordered });
      }
      if (e.progress) set({ progress: e.progress });
      else if (e.kind === "recommendation" || e.agent !== "advice") set({ progress: null });
      break;
    }

    case "done":
      void playReply();
      break;

    case "handoff":
      player.discard();
      settle();
      set({ handoff: { reference: e.reference, reason: e.reason ?? get().handoff?.reason }, progress: null });
      break;

    case "error":
      player.discard();
      settle();
      // Server messages can be technical; only the "didn't catch that" case is shown as is.
      showDockError(/catch/i.test(e.message) ? "didntCatch" : "serverError");
      break;
  }
}

async function playReply() {
  const last = [...get().timeline].reverse().find((i) => i.kind === "assistant");
  if (!player.hasPending) {
    // No audio: the language is text only (or speech failed). The text is the answer.
    if (last) updateItem(last.id, { textOnly: true });
    set({ lastTextOnly: !!last });
    return settle();
  }
  set({ lastTextOnly: false });
  settle("speaking");
  const url = await player.playCollected({
    onProgress: (elapsed, duration) => set({ speaking: { elapsed, duration } }),
    onEnd: () => {
      set({ speaking: null });
      if (get().turn === "speaking") set({ turn: "idle" });
    },
  });
  if (url && last) {
    updateItem(last.id, { audioUrl: url });
    const seconds = await audioDuration(url);
    if (seconds) updateItem(last.id, { audioSeconds: seconds });
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

export function reconnectNow() {
  socket.wake();
}

/** Call from pointerdown / keydown. */
export async function startTalking() {
  const s = get();
  if (s.turn === "speaking") stopSpeaking(); // barge in on a reply that is still playing
  if (!canTalk(get())) return;
  if (!useUi.getState().micExplained) return openSheet("mic"); // explain before the browser's prompt
  player.unlock(); // must happen synchronously inside the gesture (iOS)
  set({ turn: "starting", micError: null, dockError: null, lastTextOnly: false });
  try {
    await recorder.start(
      () => void stopTalking(),
      (level) => set({ level }),
    );
    // released before the mic opened: stopTalking already ran, so end the recording now
    if (get().turn !== "starting") return void recorder.cancel();
    set({ turn: "recording", recordingSince: Date.now() });
  } catch (err) {
    const reason = err instanceof MicUnavailable ? err.reason : "unknown";
    set({ turn: "idle", micError: reason });
    openSheet("mic");
  }
}

/** Call from pointerup / keyup, and when the 30 s limit is reached. */
export async function stopTalking() {
  const turn = get().turn;
  if (turn === "starting") return set({ turn: "idle" }); // tap too short
  if (turn !== "recording") return;
  const startedAt = get().recordingSince ?? Date.now();
  set({ recordingSince: null, level: 0 });
  const recording = await recorder.stop();
  if (!recording || Date.now() - startedAt < 400) {
    set({ turn: "idle" });
    return showDockError("tooShort");
  }
  if (!socket.sendAudio(recording)) {
    set({ turn: "idle" });
    return showDockError("notConnected");
  }
  waitForReply("sending");
}

export async function cancelTalking() {
  if (get().turn !== "recording" && get().turn !== "starting") return;
  await recorder.cancel();
  set({ turn: "idle", recordingSince: null, level: 0 });
}

/** The mic explainer's Continue: ask the browser for permission now, inside this tap. */
export async function grantMicFromExplainer() {
  useUi.setState({ micExplained: true, sheet: null });
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((t) => t.stop());
    set({ micError: null });
  } catch (err) {
    const name = (err as DOMException)?.name;
    set({ micError: name === "NotAllowedError" ? "denied" : window.isSecureContext ? "unknown" : "insecure" });
    openSheet("mic");
  }
}

export function answerConsent(granted: boolean, purpose?: ConsentPurpose) {
  const sheetPrompt = get().consentPrompt;
  const p = purpose ?? sheetPrompt?.purpose;
  if (!p) return;
  if (p === "conversation") set({ consentPrompt: null });
  else {
    const pending = [...get().timeline].reverse().find((i) => i.kind === "consent" && i.answered === null);
    if (pending) updateItem(pending.id, { answered: granted });
  }
  socket.send({ type: "consent", purpose: p, granted });
  // Granting needs_analysis makes the server answer the question that triggered it.
  if (granted && p === "needs_analysis") waitForReply("thinking");
}

/** Shows the conversation consent again after the person declined or withdrew it. */
export function reviewConsent() {
  const prompt = lastPrompt.conversation;
  if (prompt) set({ consentPrompt: prompt });
}

export function withdrawConsent(purpose: ConsentPurpose) {
  socket.send({ type: "consent", purpose, granted: false });
}

export function requestHuman() {
  stopSpeaking();
  socket.send({ type: "handoff" });
}

export function replay(url: string) {
  const turn = get().turn;
  if (turn !== "idle" && turn !== "speaking") return;
  set({ turn: "speaking" });
  void player.replay(url, {
    onProgress: (elapsed, duration) => set({ speaking: { elapsed, duration } }),
    onEnd: () => {
      set({ speaking: null });
      if (get().turn === "speaking") set({ turn: "idle" });
    },
  });
}

export function stopSpeaking() {
  player.stop();
  set({ speaking: null });
}

export function toggleMute() {
  player.setMuted(!player.muted);
  set({ muted: player.muted });
}

export function dismissDockError() {
  set({ dockError: null });
}
