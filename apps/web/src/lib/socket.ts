import { API_ROUTES, WS_UNAUTHORIZED, parseServerEvent, type ClientMessage, type ServerEvent } from "@sahaj/contracts";
import { accessToken, invalidateAccess } from "@/lib/auth";

export type ConnectionStatus = "connecting" | "open" | "reconnecting" | "offline" | "signed_out";

interface Handlers {
  onEvent: (event: ServerEvent) => void;
  onAudio: (chunk: Blob) => void;
  onStatus: (status: ConnectionStatus, info: { reconnected: boolean }) => void;
}

/**
 * The /ws/voice connection. Same origin by default (Vite proxies it in dev, FastAPI or the load balancer serves it
 * in production), so https pages automatically get wss://. Set VITE_API_URL only when the API is elsewhere.
 *
 * The server needs an access token. Browsers can't set headers on a WebSocket, so it goes in ?access_token=, fresh
 * for every connection (it is short-lived, which matters because URLs end up in logs). A 4401 close means the token
 * was rejected: refresh once and reconnect; if that fails, the person is signed out.
 *
 * Reconnects with backoff. A new socket is a new server session: the server forgets the conversation (consent and
 * an open case with a person carry over, because they belong to the account).
 */
export class VoiceSocket {
  private ws: WebSocket | null = null;
  private attempts = 0;
  private retry: ReturnType<typeof setTimeout> | null = null;
  private closedByUs = false;
  private everOpened = false;
  private pending = false;
  private authRetried = false;
  /** Bumped by close(): a connect() still waiting for its token must not open a socket for an old generation. */
  private generation = 0;

  constructor(private handlers: Handlers) {}

  static url(token: string): string {
    const base = import.meta.env.VITE_API_URL as string | undefined;
    const origin = base ? new URL(base) : new URL(window.location.href);
    const proto = origin.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${origin.host}${API_ROUTES.voiceSocket}?access_token=${encodeURIComponent(token)}`;
  }

  async connect(): Promise<void> {
    this.closedByUs = false;
    if (this.ws || this.pending) return;
    const generation = this.generation;
    this.pending = true;
    this.handlers.onStatus(this.everOpened ? "reconnecting" : "connecting", { reconnected: false });
    const token = await accessToken().finally(() => (this.pending = false));
    if (this.closedByUs || generation !== this.generation || this.ws) return;
    if (!token) {
      if (!navigator.onLine) return this.handlers.onStatus("offline", { reconnected: false });
      return this.handlers.onStatus("signed_out", { reconnected: false });
    }
    const ws = new WebSocket(VoiceSocket.url(token));
    ws.binaryType = "blob";
    this.ws = ws;

    ws.onopen = () => {
      const reconnected = this.everOpened;
      this.everOpened = true;
      this.attempts = 0;
      this.authRetried = false;
      this.handlers.onStatus("open", { reconnected });
    };
    ws.onmessage = ({ data }) => {
      if (data instanceof Blob) return this.handlers.onAudio(data);
      const event = parseServerEvent(data as string);
      if (event) this.handlers.onEvent(event);
    };
    ws.onclose = (e) => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (this.closedByUs) return;
      if (e.code === WS_UNAUTHORIZED) {
        invalidateAccess();
        if (this.authRetried) return this.handlers.onStatus("signed_out", { reconnected: false });
        this.authRetried = true; // one fresh token; a second rejection means the session is really over
        return void this.connect();
      }
      this.handlers.onStatus(navigator.onLine ? "reconnecting" : "offline", { reconnected: false });
      this.scheduleReconnect();
    };
  }

  send(message: ClientMessage): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(message));
    return true;
  }

  sendAudio(recording: Blob): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(recording);
    return true;
  }

  /** Reconnect now (e.g. the app came back to the foreground or the network returned). */
  wake(): void {
    if (this.ws || this.closedByUs) return;
    if (this.retry) clearTimeout(this.retry);
    this.retry = null;
    void this.connect();
  }

  close(): void {
    this.closedByUs = true;
    this.generation++;
    this.pending = false;
    if (this.retry) clearTimeout(this.retry);
    this.retry = null;
    this.ws?.close();
    this.ws = null;
    this.everOpened = false;
  }

  private scheduleReconnect() {
    const delay = Math.min(1000 * 2 ** this.attempts, 15000) + Math.random() * 500;
    this.attempts++;
    this.retry = setTimeout(() => {
      this.retry = null;
      void this.connect();
    }, delay);
  }
}
