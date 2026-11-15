import type { ConsentPurpose, ConsentRequiredEvent, ServerEvent } from "@sahaj/contracts";
import { audioDuration, player } from "@/lib/audio/player";
import { MicUnavailable, Recorder } from "@/lib/audio/recorder";
import { api } from "@/lib/auth";
import type { StringKey } from "@/lib/i18n";
import { VoiceSocket } from "@/lib/socket";
import { canTalk, initialSession, pushItem, updateItem, useSession, withPerson } from "@/store/session";
import { openSheet, useUi } from "@/store/ui";

/**
 * Side effects of a conversation: the socket, the mic and the speaker. Components read `useSession` and call
 * these functions; nothing else touches the socket.
 */

const set = useSession.setState;
const get = useSession.getState;

/** Give up on a turn that gets no reply (the server normally answers within a few seconds). */
const TURN_TIMEOUT_MS = 60_000;
/**
 * Below this peak amplitude (0..1) a recording is treated as silence. Speech peaks well above 0.05 even when quiet;
 * a muted mic or noise-suppressed silence stays under ~0.005. Kept low so quiet speakers are never blocked.
 */
const QUIET_PEAK = 0.008;
/** Practically no signal: the microphone itself is muted, the wrong device, or blocked by the operating system. */
const MUTED_PEAK = 0.0005;
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

/** A string key, or a message from the server that is meant for the person. */
function showDockError(message: StringKey | string) {
  set({ dockError: message });
  if (dockErrorTimer) clearTimeout(dockErrorTimer);
  dockErrorTimer = setTimeout(() => set({ dockError: null }), 8000);
}

/** Server error messages written for people (not exceptions): show them as they are. */
function isPlainMessage(message: string) {
  return message.length <= 160 && !/[{}[\]<>]|error|exception|traceback|http|psycopg|status code|\.py\b/i.test(message);
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
      // A new socket is a new server session: it forgot the conversation. Consent and an open case belong to the
      // account and come back in the `session` event.
      set({
        consentPrompt: null, sessionId: null, progress: null,
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

const CONSENT_NOTE: Partial<Record<ConsentPurpose, [StringKey, StringKey]>> = {
  conversation: ["consentGranted", "consentWithdrawn"],
  needs_analysis: ["detailsGranted", "detailsWithdrawn"],
};

function handleEvent(e: ServerEvent) {
  switch (e.type) {
    case "session": {
      const consent = { ...initialSession.consent };
      for (const [purpose, granted] of Object.entries(e.consents ?? {})) {
        if (purpose in consent) consent[purpose as ConsentPurpose] = { state: granted ? "granted" : "unknown" };
      }
      set((s) => ({
        sessionId: e.id, user: e.user, consent: { ...s.consent, ...consent },
        declined: consent.conversation.state === "granted" ? false : s.declined,
        handoff: e.case ? { reference: e.case.reference, case: e.case, agentName: null } : null,
      }));
      void loadConsentDetails();
      break;
    }

    case "consent_required":
      lastPrompt[e.purpose] = e;
      if (e.purpose === "conversation") {
        set({ consentPrompt: e });
        // Audio sent without consent gets only this reply (no `done`), so the turn ends here.
        if (get().turn === "thinking" || get().turn === "sending") settle();
      } else {
        // Other permissions (personal details, video KYC…) are asked inside the conversation, as a card.
        pushItem({ kind: "consent", prompt: e, answered: null });
      }
      break;

    case "consent": {
      const prompt = lastPrompt[e.purpose];
      set((s) => ({
        consent: { ...s.consent, [e.purpose]: { state: e.status, version: prompt?.version ?? s.consent[e.purpose]?.version, at: Date.now() } },
        declined: e.purpose === "conversation" ? e.status === "revoked" : s.declined,
      }));
      const note = CONSENT_NOTE[e.purpose];
      if (note) {
        pushItem(e.status === "granted"
          ? { kind: "system", icon: "verified_user", text: note[0], tone: "success" }
          : { kind: "system", icon: "remove_moderator", text: note[1] });
      }
      if (e.purpose === "needs_analysis" && e.status === "revoked") set({ progress: null });
      break;
    }

    case "user":
      set({ dockError: null });
      pushItem({ kind: "user", text: e.text });
      if (withPerson(get())) settle(); // passed on to the person handling the case: no AI reply follows
      else if (get().turn === "sending") waitForReply("thinking"); // transcribed: now Sahaj is working on it
      break;

    case "status":
      if (e.stage === "waiting_for_executive") return settle();
      if (e.stage === "speaking" || e.stage === "speech_unavailable") break;
      set((s) => ({
        status: e.stage,
        statusHistory: s.statusHistory.includes(e.stage) ? s.statusHistory : [...s.statusHistory, e.stage],
        turn: s.turn === "sending" && e.stage !== "transcribing" ? "thinking" : s.turn,
      }));
      break;

    case "usage_warning":
      set((s) => ({ budget: { ...s.budget, warned: true } }));
      pushItem({ kind: "system", icon: "info", text: "budgetWarning", vars: { pct: Math.round(e.percent_used) } });
      break;

    case "budget_exceeded":
      player.discard();
      settle();
      set((s) => ({ budget: { ...s.budget, exceededUntil: e.resets_at } }));
      break;

    case "card":
      pushItem({ kind: "card", card: e.card, traceId: e.trace_id });
      if (useUi.getState().panelItemId) useUi.setState({ panelItemId: null }); // panel follows the newest card
      break;

    case "assistant": {
      pushItem({
        kind: "assistant", agent: e.agent, text: e.text, citations: e.citations, traceId: e.trace_id,
        replyKind: e.kind ?? "answer", fallback: !!e.fallback, audioUrl: null, audioSeconds: null, textOnly: false,
        verification: e.verification ?? null, suggestions: e.suggestions ?? [], feedback: null,
      });
      // The server asks for a permission just before the message that explains why;
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

    // ---------- a person from the team ----------
    case "handoff":
      player.discard();
      settle();
      set({ handoff: { reference: e.reference, reason: e.reason, case: e.case, agentName: null }, progress: null });
      break;

    case "agent_joined":
      set((s) => ({ handoff: s.handoff && { ...s.handoff, agentName: e.agent.name, case: s.handoff.case && { ...s.handoff.case, status: "with_executive" } } }));
      pushItem({ kind: "system", icon: "support_agent", text: "agentJoined", tone: "success", vars: { name: e.agent.name } });
      break;

    case "agent_message":
      pushItem({ kind: "agent", name: e.agent.name, text: e.text });
      break;

    case "agent_left":
      set((s) => ({ handoff: s.handoff && { ...s.handoff, agentName: null, case: s.handoff.case && { ...s.handoff.case, status: "waiting" } } }));
      pushItem({ kind: "system", icon: "support_agent", text: "agentLeft" });
      break;

    case "video_kyc_scheduled":
      pushItem({ kind: "system", icon: "event_available", text: "kycScheduled", tone: "success",
        vars: { when: new Date(e.scheduled_for).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) } });
      break;

    case "handoff_closed": {
      const name = get().handoff?.agentName ?? "";
      set({ handoff: null });
      if (e.message) pushItem({ kind: "agent", name, text: e.message });
      pushItem({ kind: "system", icon: "restart_alt", text: e.status === "resolved" ? "caseResolved" : "caseCancelled" });
      break;
    }

    case "error":
      player.discard();
      settle();
      if (get().budget.exceededUntil) break; // the budget banner already says why
      showDockError(/catch/i.test(e.message) ? "didntCatch" : isPlainMessage(e.message) ? e.message : "serverError");
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

/** Versions and dates of the account's consents, for the menu (the socket only says on/off). */
async function loadConsentDetails() {
  try {
    const { items } = await api<import("@sahaj/contracts").ConsentsResponse>("/consents");
    set((s) => {
      const consent = { ...s.consent };
      for (const item of items) {
        if (!(item.purpose in consent)) continue;
        const purpose = item.purpose as ConsentPurpose;
        consent[purpose] = {
          state: item.granted ? "granted" : consent[purpose].state === "revoked" ? "revoked" : "unknown",
          version: item.granted_version ?? item.version,
          at: item.granted_at ? item.granted_at * 1000 : undefined,
        };
        // the text the person agreed to, so the menu can show it again and a later grant echoes the right version
        lastPrompt[purpose] ??= { type: "consent_required", purpose, title: item.title, version: item.version, text: item.text,
          required: item.required, requires: item.requires as ConsentPurpose | null, withdrawal: item.withdrawal };
      }
      return { consent };
    });
  } catch {
    /* the menu just shows less detail */
  }
}

// ---------------------------------------------------------------- public API

const recorder = new Recorder();
let listening = false;

/** Opens the conversation (after sign-in). */
export function connect() {
  void socket.connect();
  if (listening) return;
  listening = true;
  const wake = () => document.visibilityState === "visible" && socket.wake();
  // iOS closes sockets when the app is backgrounded or the phone locks; reconnect on return.
  document.addEventListener("visibilitychange", wake);
  window.addEventListener("online", wake);
  window.addEventListener("pageshow", wake);
}

/** Closes the conversation and forgets it (sign-out). */
export function disconnect() {
  socket.close();
  player.stop();
  void recorder.cancel();
  if (turnTimer) clearTimeout(turnTimer);
  for (const key of Object.keys(lastPrompt)) delete lastPrompt[key as ConsentPurpose];
  set({ ...initialSession }); // "connecting" again; "signed_out" is only for a session the server rejected
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
  // Silence isn't sent: speech-to-text tends to "hear" a word in some language in it, which Sahaj would answer.
  if (import.meta.env.DEV) console.info(`[sahaj] recording ${recording.size} bytes, peak ${recorder.peak?.toFixed(4) ?? "n/a"}`);
  if (recorder.peak !== null && recorder.peak < QUIET_PEAK) {
    set({ turn: "idle" });
    // No signal at all is a microphone problem (muted, wrong device, or blocked by the OS), not a quiet speaker.
    return showDockError(recorder.peak < MUTED_PEAK ? "micSilent" : "tooQuiet");
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

/** A follow-up chip: sent as a typed message, answered aloud like a spoken one. Call from a tap. */
export function sendSuggestion(text: string) {
  if (!canTalk(get())) return;
  if (get().turn === "speaking") stopSpeaking();
  player.unlock(); // the reply is spoken, and this tap is the gesture iOS needs
  if (!socket.send({ type: "text", text, speak: true })) return showDockError("notConnected");
  set({ dockError: null, lastTextOnly: false });
  waitForReply(withPerson(get()) ? "sending" : "thinking");
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
  const p = purpose ?? get().consentPrompt?.purpose;
  if (!p) return;
  const version = (p === "conversation" ? get().consentPrompt : lastPrompt[p])?.version;
  if (p === "conversation") set({ consentPrompt: null });
  else {
    const pending = [...get().timeline].reverse().find((i) => i.kind === "consent" && i.prompt.purpose === p && i.answered === null);
    if (pending) updateItem(pending.id, { answered: granted });
  }
  // The version of the text that was shown: the server records the grant against it (and refuses a stale one).
  socket.send({ type: "consent", purpose: p, granted, version });
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
  if (withPerson(get())) return;
  stopSpeaking();
  socket.send({ type: "handoff" });
}

/** The person no longer needs the team: the AI answers again. */
export function cancelHandoff() {
  socket.send({ type: "handoff_cancel" });
}

/** Thumbs up/down on a reply. Rating again replaces the earlier one. */
export async function rateReply(itemId: string, traceId: string, rating: "up" | "down") {
  updateItem(itemId, { feedback: rating });
  try {
    await api("/feedback", { method: "POST", body: JSON.stringify({ trace_id: traceId, rating }) });
  } catch {
    updateItem(itemId, { feedback: null });
    showDockError("feedbackFailed");
  }
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
