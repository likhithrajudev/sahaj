import type { AuthConfig, AuthSession, User } from "@sahaj/contracts";
import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Sign-in and the access token.
 *
 * - The access token (15 min) lives only in memory. The refresh token is kept in localStorage so the installed PWA
 *   stays signed in; each refresh token works once (the server rotates it), so refreshes are serialised: two
 *   parallel refreshes would spend the same token and the second would sign the person out.
 * - Every API call goes through `api()`, which adds the token and refreshes once on a 401.
 */

interface AuthState {
  user: User | null;
  refreshToken: string | null;
}

export const useAuth = create<AuthState>()(
  persist((): AuthState => ({ user: null, refreshToken: null }), { name: "sahaj-auth" }),
);

let access: { token: string; expiresAt: number } | null = null;
let refreshing: Promise<string | null> | null = null;

function accept(session: AuthSession) {
  access = { token: session.access_token, expiresAt: Date.now() + session.expires_in * 1000 };
  useAuth.setState({ user: session.user, refreshToken: session.refresh_token });
}

export class AuthError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) {
    const detail = await r.json().catch(() => null);
    const message = typeof detail?.detail === "string" ? detail.detail : detail?.detail?.message;
    throw new AuthError(message || `Request failed (${r.status})`, r.status);
  }
  return r.status === 204 ? (undefined as T) : r.json();
}

/**
 * A valid access token, refreshing it if it is missing or about to expire. null = none right now: either signed out
 * (`useAuth` has no refresh token any more) or the refresh could not be done (network, server restarting); try later.
 */
export async function accessToken(): Promise<string | null> {
  if (access && access.expiresAt - Date.now() > 30_000) return access.token;
  return refresh();
}

function refresh(): Promise<string | null> {
  if (refreshing) return refreshing; // one refresh at a time: refresh tokens are single-use
  const token = useAuth.getState().refreshToken;
  if (!token) return Promise.resolve(null);
  refreshing = post<AuthSession>("/auth/refresh", { refresh_token: token })
    .then((s) => {
      accept(s);
      return s.access_token;
    })
    .catch((e) => {
      // Only the server refusing the token (401) ends the session: it expired, was revoked or was reused. A network
      // error, a rate limit or a server that is restarting (429, 5xx) is temporary: keep the session and try later.
      if (e instanceof AuthError && e.status === 401) signedOut();
      return null;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

/** Forces a new access token (the socket was closed with 4401). */
export function invalidateAccess() {
  access = null;
}

export async function getAuthConfig(): Promise<AuthConfig> {
  const r = await fetch("/auth/config");
  if (!r.ok) throw new Error(`Sign-in is unavailable (${r.status})`);
  return r.json();
}

export async function signInWithGoogle(idToken: string) {
  accept(await post<AuthSession>("/auth/google", { id_token: idToken, platform: "web" }));
}

function signedOut() {
  access = null;
  useAuth.setState({ user: null, refreshToken: null });
}

export async function signOut() {
  const token = useAuth.getState().refreshToken;
  signedOut();
  if (token) await post("/auth/logout", { refresh_token: token }).catch(() => {});
}

/** fetch() for the Sahaj API: adds the access token and retries once after a refresh on 401. */
export async function apiResponse(path: string, init: RequestInit = {}): Promise<Response> {
  const call = async (token: string | null) =>
    fetch(path, {
      ...init,
      headers: {
        ...(init.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
  let r = await call(await accessToken());
  if (r.status === 401) {
    invalidateAccess();
    r = await call(await refresh());
  }
  if (!r.ok) {
    const detail = await r.json().catch(() => null);
    const message = typeof detail?.detail === "string" ? detail.detail : detail?.detail?.message;
    throw new Error(message || `Request failed (${r.status})`);
  }
  return r;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiResponse(path, init);
  return response.status === 204 ? (undefined as T) : response.json();
}
