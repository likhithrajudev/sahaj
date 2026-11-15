import type { AuthSession, User } from "@sahaj/contracts";

const KEY = "sahaj.session";
type Stored = { access: string; refresh: string; user: User };

function load(): Stored | null {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "null");
  } catch {
    return null;
  }
}

let session: Stored | null = load();
const listeners = new Set<() => void>();

function save(next: Stored | null) {
  session = next;
  try {
    next ? localStorage.setItem(KEY, JSON.stringify(next)) : localStorage.removeItem(KEY);
  } catch {
    /* private mode: keep it in memory */
  }
  listeners.forEach((fn) => fn());
}

export const auth = {
  get user(): User | null {
    return session?.user ?? null;
  },
  get token(): string | null {
    return session?.access ?? null;
  },
  subscribe(fn: () => void) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
  set(s: AuthSession) {
    save({ access: s.access_token, refresh: s.refresh_token, user: s.user });
  },
  setUser(user: User) {
    if (session) save({ ...session, user });
  },
  async signOut() {
    if (session) await fetch("/auth/logout", { method: "POST", headers: json, body: JSON.stringify({ refresh_token: session.refresh }) }).catch(() => {});
    save(null);
  },
  async refresh(): Promise<boolean> {
    if (!session) return false;
    const r = await fetch("/auth/refresh", { method: "POST", headers: json, body: JSON.stringify({ refresh_token: session.refresh }) });
    if (!r.ok) {
      save(null);
      return false;
    }
    this.set(await r.json());
    return true;
  },
};

const json = { "content-type": "application/json" };

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: unknown) {
    super(message);
  }
}

function message(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  return fallback;
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}, retry = true): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (session) headers.authorization = `Bearer ${session.access}`;
  let body = init.body;
  if (init.json !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  const r = await fetch(path, { ...init, headers, body });
  if (r.status === 401 && retry && (await auth.refresh())) return api(path, init, false);
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new ApiError(message(data.detail, r.statusText), r.status, data.detail);
  }
  if (r.status === 204) return undefined as T;
  const type = r.headers.get("content-type") || "";
  return (type.includes("json") ? r.json() : r.blob()) as Promise<T>;
}

export async function signIn(path: "/auth/google" | "/auth/dev", body: unknown) {
  const r = await fetch(path, { method: "POST", headers: json, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(message(data.detail, "Sign-in failed"), r.status);
  auth.set(data);
  return data as AuthSession;
}

export function socketUrl(path: string, params: Record<string, string | undefined> = {}) {
  const url = new URL(path, location.href);
  url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
  if (session) url.searchParams.set("access_token", session.access);
  Object.entries(params).forEach(([k, v]) => v && url.searchParams.set(k, v));
  return url.toString();
}

export const isStaff = (u: User | null) => !!u && (u.role === "admin" || u.role === "executive");
export const isAdmin = (u: User | null) => u?.role === "admin";

export function download(blob: Blob, name: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
