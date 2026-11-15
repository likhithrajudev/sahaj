import { API_ROUTES, parseServerEvent, type ClientMessage, type ServerEvent } from "@sahaj/contracts";

export type ConnectionStatus = "connecting" | "open" | "reconnecting" | "offline";

interface Handlers {
  onEvent: (event: ServerEvent) => void;
  onAudio: (chunk: Blob) => void;
  onStatus: (status: ConnectionStatus, info: { reconnected: boolean }) => void;
}

/**
 * The /ws/voice connection. Same origin by default (Vite proxies it in dev, FastAPI or the load balancer
 * serves it in production), so https pages automatically get wss://. Set VITE_API_URL only when the API is
 * on another origin.
 *
 * Reconnects with backoff. A new socket is a new server session: the server forgets the conversation and
 * asks for consent again, so callers must reset their state on `reconnected`.
 */
export class VoiceSocket {
  private ws: WebSocket | null = null;
  private attempts = 0;
  private retry: ReturnType<typeof setTimeout> | null = null;
  private closedByUs = false;
  private everOpened = false;

  constructor(private handlers: Handlers) {}

  static url(): string {
    const base = import.meta.env.VITE_API_URL as string | undefined;
    const origin = base ? new URL(base) : new URL(window.location.href);
    const proto = origin.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${origin.host}${API_ROUTES.voiceSocket}`;
  }

  connect(): void {
    this.closedByUs = false;
    this.handlers.onStatus(this.everOpened ? "reconnecting" : "connecting", { reconnected: false });
    const ws = new WebSocket(VoiceSocket.url());
    ws.binaryType = "blob";
    this.ws = ws;

    ws.onopen = () => {
      const reconnected = this.everOpened;
      this.everOpened = true;
      this.attempts = 0;
      this.handlers.onStatus("open", { reconnected });
    };
    ws.onmessage = ({ data }) => {
      if (data instanceof Blob) return this.handlers.onAudio(data);
      const event = parseServerEvent(data as string);
      if (event) this.handlers.onEvent(event);
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (this.closedByUs) return;
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
    this.connect();
  }

  close(): void {
    this.closedByUs = true;
    if (this.retry) clearTimeout(this.retry);
    this.ws?.close();
    this.ws = null;
  }

  private scheduleReconnect() {
    const delay = Math.min(1000 * 2 ** this.attempts, 15000) + Math.random() * 500;
    this.attempts++;
    this.retry = setTimeout(() => {
      this.retry = null;
      this.connect();
    }, delay);
  }
}
