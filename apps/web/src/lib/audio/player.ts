/**
 * Plays Sahaj's spoken reply (MP3 chunks sent over the socket, joined on `done`).
 *
 * iPhone notes:
 * - iOS only lets audio start inside a user gesture, but the reply arrives seconds after the user lets go of
 *   the talk button. unlock() runs during the press and plays a silent clip on one long-lived <audio>
 *   element; iOS then lets that same element play later without a gesture.
 * - An <audio> element (unlike Web Audio) still plays when the ring/silent switch is on silent.
 */

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

class Player {
  private el: HTMLAudioElement | null = null;
  private silence: string | null = null;
  private chunks: BlobPart[] = [];
  private lastUrl_: string | null = null;
  private onEnd: (() => void) | null = null;

  private element(): HTMLAudioElement {
    if (!this.el) {
      this.el = new Audio();
      this.el.setAttribute("playsinline", "");
      this.el.preload = "auto";
      this.el.onended = () => this.ended();
      this.el.onerror = () => this.ended();
    }
    return this.el;
  }

  /** Call synchronously inside a pointerdown/keydown handler, before any await. */
  unlock(): void {
    // iOS 17+: treat our audio as media playback, not an ambient sound
    const session = (navigator as Navigator & { audioSession?: { type: string } }).audioSession;
    if (session) session.type = "playback";
    const el = this.element();
    if (!el.paused) return;
    this.silence ??= silentWav();
    el.src = this.silence;
    el.play().catch(() => {});
  }

  push(chunk: BlobPart): void {
    this.chunks.push(chunk);
  }

  /** Drops chunks of an unfinished reply (e.g. after an error). */
  discard(): void {
    this.chunks = [];
  }

  /**
   * Plays the collected chunks. Returns the reply's URL (keep it for replay), or null if there was no audio.
   * `onEnd` fires when playback ends, fails, or is stopped.
   */
  async playCollected(onEnd?: () => void): Promise<string | null> {
    if (!this.chunks.length) return null;
    const url = URL.createObjectURL(new Blob(this.chunks, { type: "audio/mpeg" }));
    this.chunks = [];
    if (this.lastUrl_) URL.revokeObjectURL(this.lastUrl_); // one reply's audio kept at a time
    this.lastUrl_ = url;
    await this.play(url, onEnd);
    return url;
  }

  /** Replays a reply. Call from a tap, so it is always allowed. */
  replay(url: string, onEnd?: () => void): Promise<boolean> {
    return this.play(url, onEnd);
  }

  stop(): void {
    if (this.el && !this.el.paused) this.el.pause();
    this.ended();
  }

  private async play(url: string, onEnd?: () => void): Promise<boolean> {
    this.stop();
    this.onEnd = onEnd ?? null;
    const el = this.element();
    el.src = url;
    try {
      await el.play();
      return true;
    } catch {
      this.ended(); // blocked or undecodable: the text is still on screen
      return false;
    }
  }

  private ended() {
    const cb = this.onEnd;
    this.onEnd = null;
    cb?.();
  }
}

export const player = new Player();
