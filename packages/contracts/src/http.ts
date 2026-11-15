/** REST endpoints. Source of truth: docs/voice-api.md ("Other endpoints"). */

export interface HealthResponse {
  status: "ok";
}

/** POST /stt (multipart `file`, up to 30 seconds of audio). */
export interface SttResponse {
  text: string;
  language: string;
}

// ---------- Accounts ----------

export type Platform = "web" | "android" | "ios";
export type Role = "user" | "admin";

export interface User {
  id: string;
  email: string;
  name: string | null;
  picture: string | null;
  /** BCP-47 tag such as "en-IN" or "hi-IN". */
  language: string;
  platform: Platform;
  role: Role;
}

/** POST /auth/google. `id_token` is the ID token Google gives the client after sign-in. */
export interface GoogleLoginRequest {
  id_token: string;
  platform?: Platform;
}

/** Response of POST /auth/google and POST /auth/refresh. Each refresh token can be used once. */
export interface AuthSession {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  /** Seconds until the access token expires. */
  expires_in: number;
  user: User;
}

/** POST /auth/refresh and POST /auth/logout (204). */
export interface RefreshRequest {
  refresh_token: string;
}

/** GET /users/me */
export interface Me extends User {
  memory_consent: boolean;
}

/** PATCH /users/me */
export interface ProfileUpdate {
  name?: string;
  language?: string;
  platform?: Platform;
}

export interface MemoryItem {
  id: number;
  kind: "fact" | "summary";
  key: string | null;
  content: string;
  created_at: string;
  updated_at: string;
}

/** GET /users/me/memory */
export interface MemoryResponse {
  consent: boolean;
  /** Show `consent_text.text` verbatim before asking for consent. */
  consent_text: { purpose: "memory"; version: string; text: string };
  items: MemoryItem[];
}

/** PUT /users/me/memory/consent. Withdrawing erases everything remembered. */
export interface MemoryConsentRequest {
  granted: boolean;
}

export interface MemoryConsentResponse {
  consent: boolean;
  erased: number;
}

/** POST /chat/stream: the voice protocol over HTTP. The response is a Server-Sent Events stream of ServerEvent JSON. */
export interface ChatStreamRequest {
  /** Omit to start a conversation; pass the id from its `session` event to continue it. */
  session_id?: string;
  message: import("./voice").ClientMessage;
}

export const API_ROUTES = {
  health: "/health",
  stt: "/stt",
  voiceSocket: "/ws/voice",
  authGoogle: "/auth/google",
  authRefresh: "/auth/refresh",
  authLogout: "/auth/logout",
  me: "/users/me",
  memory: "/users/me/memory",
  memoryConsent: "/users/me/memory/consent",
  adminUsers: "/admin/users",
  chatStream: "/chat/stream",
  chat: "/chat",
} as const;
