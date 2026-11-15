/** REST endpoints. Source of truth: docs/voice-api.md ("Other endpoints"). */

export interface HealthResponse {
  status: "ok";
}

/** POST /stt (multipart `file`, up to 30 seconds of audio). */
export interface SttResponse {
  text: string;
  language: string;
}

export const API_ROUTES = {
  health: "/health",
  stt: "/stt",
  voiceSocket: "/ws/voice",
} as const;
