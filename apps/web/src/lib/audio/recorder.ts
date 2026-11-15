import { MAX_RECORDING_SECONDS } from "@sahaj/contracts";
import { setAudioSession } from "./player";

/**
 * Push-to-talk recorder.
 *
 * iPhone notes:
 * - Safari records audio/mp4 (AAC), not WebM. We let the browser pick from a preference list; the backend
 *   detects the container from the bytes (apps/api/services/audio.py).
 * - The mic stream is opened per recording and fully released afterwards. While a mic track is live, iOS
 *   routes playback to the quiet earpiece, so Sahaj's spoken reply would be barely audible.
 * - getUserMedia needs a secure context: https:// or localhost.
 */

const PREFERRED_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4;codecs=mp4a.40.2", "audio/mp4", "audio/aac"];

export type MicError = "unsupported" | "insecure" | "denied" | "no-device" | "unknown";

export class MicUnavailable extends Error {
  constructor(public reason: MicError, cause?: unknown) {
    super(reason);
    this.cause = cause;
  }
}

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) return undefined;
  return PREFERRED_TYPES.find((t) => MediaRecorder.isTypeSupported(t));
}

export class Recorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private parts: Blob[] = [];
  private limitTimer: ReturnType<typeof setTimeout> | null = null;
  private finished: Promise<Blob | null> | null = null;
  private cancelled = false;

  private meter: { ctx: AudioContext; raf: number } | null = null;
  /** Loudest level seen in this recording (0..1), or null when the browser didn't let us measure. */
  peak: number | null = null;

  /**
   * Starts recording. Resolves once the mic is live. Call from a pointer/keyboard handler.
   * `onLevel` receives the input loudness (0..1) about 30 times a second, when the browser allows measuring it.
   */
  async start(onLimit?: () => void, onLevel?: (level: number) => void): Promise<void> {
    if (!window.isSecureContext) throw new MicUnavailable("insecure");
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      throw new MicUnavailable("unsupported");
    }
    setAudioSession("auto"); // let iOS switch to play-and-record for the capture
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) {
      const name = (e as DOMException)?.name;
      throw new MicUnavailable(
        name === "NotAllowedError" || name === "SecurityError" ? "denied" : name === "NotFoundError" ? "no-device" : "unknown",
        e,
      );
    }

    const mimeType = pickMimeType();
    this.parts = [];
    this.cancelled = false;
    this.peak = null;
    this.recorder = new MediaRecorder(this.stream, mimeType ? { mimeType } : undefined);
    this.recorder.ondataavailable = (e) => e.data.size && this.parts.push(e.data);
    this.finished = new Promise((resolve) => {
      this.recorder!.onstop = () => {
        const type = this.recorder?.mimeType || mimeType || "audio/webm";
        this.release();
        resolve(this.cancelled || !this.parts.length ? null : new Blob(this.parts, { type }));
      };
    });
    this.recorder.start();
    if (onLevel) this.startMeter(this.stream, onLevel);
    this.limitTimer = setTimeout(() => onLimit?.(), MAX_RECORDING_SECONDS * 1000 - 250);
  }

  /** Stops and returns the recording, or null if nothing was captured. */
  async stop(): Promise<Blob | null> {
    if (!this.recorder || this.recorder.state === "inactive") return this.finished ?? null;
    this.recorder.stop();
    return this.finished;
  }

  /** Stops and discards. */
  async cancel(): Promise<void> {
    this.cancelled = true;
    await this.stop();
  }

  /** The live mic stream while recording, e.g. for a level meter. */
  get liveStream(): MediaStream | null {
    return this.stream;
  }

  private startMeter(stream: MediaStream, onLevel: (level: number) => void) {
    try {
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new Ctx();
      void ctx.resume().catch(() => {});
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (const v of data) sum += ((v - 128) / 128) ** 2;
        const level = Math.min(1, Math.sqrt(sum / data.length) * 4); // speech RMS is ~0.05-0.25
        // a suspended context reads flat silence: only count it once audio is really flowing
        if (ctx.state === "running") this.peak = Math.max(this.peak ?? 0, level);
        onLevel(level);
        if (this.meter) this.meter.raf = requestAnimationFrame(tick);
      };
      this.meter = { ctx, raf: requestAnimationFrame(tick) };
    } catch {
      this.meter = null; // no level: the UI animates the bars on its own
    }
  }

  private release() {
    if (this.meter) {
      cancelAnimationFrame(this.meter.raf);
      void this.meter.ctx.close().catch(() => {});
      this.meter = null;
    }
    if (this.limitTimer) clearTimeout(this.limitTimer);
    this.limitTimer = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
  }
}
