/**
 * Plays Sahaj's spoken reply (MP3 chunks sent over the socket, joined on `done`).
 *
 * iPhone notes:
 * - iOS only lets audio start inside a user gesture, but the reply arrives seconds after the user lets go of
 *   the talk button. unlock() runs during the press and plays a silent clip on one long-lived <audio>
 *   element; iOS then lets that same element play later without a gesture.
 * - An <audio> element (unlike Web Audio) still plays when the ring/silent switch is on silent.
 * - The audio session is switched to "playback" only after the mic is released (see setAudioSession), so the
 *   reply uses the loudspeaker and recording is never disturbed.
 */

type AudioSessionType = "auto" | "playback" | "play-and-record";

/** iOS 17+ Safari: how our audio mixes with the system. No-op elsewhere. */
export function setAudioSession(type: AudioSessionType) {
  const session = (navigator as Navigator & { audioSession?: { type: string } }).audioSession;
  if (session) {
    try {
      session.type = type;
    } catch {
      /* not allowed right now; the default works */
    }
  }
}

/** A valid 50 ms silent WAV, built in code so there is no opaque base64 to trust. */
function silentWav(): string {
  const rate = 8000;
  const samples = rate / 20;
  const buf = new ArrayBuffer(44 + samples);
  const v = new DataView(buf);
  const str = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF");
  v.setUint32(4, 36 + samples, true);
  str(8, "WAVEfmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // mono
  v.setUint32(24, rate, true);
  v.setUint32(28, rate, true);
  v.setUint16(32, 1, true);
  v.setUint16(34, 8, true); // 8-bit
  str(36, "data");
  v.setUint32(40, samples, true);
  for (let i = 0; i < samples; i++) v.setUint8(44 + i, 128); // 8-bit silence is 128
  return URL.createObjectURL(new Blob([buf], { type: "audio/wav" }));
}

export interface PlayCallbacks {
  onProgress?: (elapsed: number, duration: number) => void;
  onEnd?: () => void;
}

class Player {
  private el: HTMLAudioElement | null = null;
  private silence: string | null = null;
  private chunks: BlobPart[] = [];
  private lastUrl: string | null = null;
  private cb: PlayCallbacks = {};
  private muted_ = false;

  private element(): HTMLAudioElement {
    if (!this.el) {
      const el = new Audio();
      el.setAttribute("playsinline", "");
      el.preload = "auto";
      el.onended = () => this.ended();
      el.onerror = () => this.ended();
      el.ontimeupdate = () => this.progress();
      el.onloadedmetadata = () => this.progress();
      this.el = el;
    }
    return this.el;
  }

  /** Call synchronously inside a pointerdown/keydown handler, before any await. */
  unlock(): void {
    const el = this.element();
    if (!el.paused) return;
    this.silence ??= silentWav();
    el.src = this.silence;
    el.play().catch(() => {});
  }

  push(chunk: BlobPart): void {
    this.chunks.push(chunk);
  }

  get hasPending(): boolean {
    return this.chunks.length > 0;
  }

  /** Drops chunks of an unfinished reply (e.g. after an error). */
  discard(): void {
    this.chunks = [];
  }

  get muted(): boolean {
    return this.muted_;
  }

  setMuted(muted: boolean): void {
    this.muted_ = muted;
    if (this.el) this.el.muted = muted;
  }

  /** Plays the collected chunks. Returns the reply's URL (keep it for replay), or null if there was no audio. */
  async playCollected(cb: PlayCallbacks = {}): Promise<string | null> {
    if (!this.chunks.length) return null;
    const url = URL.createObjectURL(new Blob(this.chunks, { type: "audio/mpeg" }));
    this.chunks = [];
    if (this.lastUrl) URL.revokeObjectURL(this.lastUrl); // one reply's audio kept at a time
    this.lastUrl = url;
    await this.play(url, cb);
    return url;
  }

  /** Replays a reply. Call from a tap, so it is always allowed. */
  replay(url: string, cb: PlayCallbacks = {}): Promise<boolean> {
    return this.play(url, cb);
  }

  /** Length of an audio URL in seconds (for "Replay · 0:18"). */
  static duration(url: string): Promise<number | null> {
    return new Promise((resolve) => {
      const probe = new Audio();
      probe.preload = "metadata";
      probe.onloadedmetadata = () => resolve(Number.isFinite(probe.duration) ? probe.duration : null);
      probe.onerror = () => resolve(null);
      probe.src = url;
    });
  }

  stop(): void {
    if (this.el && !this.el.paused) this.el.pause();
    this.ended();
  }

  private async play(url: string, cb: PlayCallbacks): Promise<boolean> {
    this.stop();
    this.cb = cb;
    setAudioSession("playback"); // the mic is released by now: use the loudspeaker
    const el = this.element();
    el.muted = this.muted_;
    el.src = url;
    try {
      await el.play();
      return true;
    } catch {
      this.ended(); // blocked or undecodable: the text is still on screen
      return false;
    }
  }

  private progress() {
    const el = this.el;
    if (!el || !this.cb.onProgress || el.src === this.silence) return;
    const duration = Number.isFinite(el.duration) ? el.duration : 0;
    this.cb.onProgress(el.currentTime, duration);
  }

  private ended() {
    const cb = this.cb;
    this.cb = {};
    cb.onEnd?.();
  }
}

export const player = new Player();
export const audioDuration = Player.duration;
