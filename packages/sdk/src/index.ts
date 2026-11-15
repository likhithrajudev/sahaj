export type Platform = "web" | "android" | "ios";

export interface SahajUser {
  id: string;
  email: string;
  name: string | null;
  picture: string | null;
  language: string;
  platform: Platform;
  role: "user" | "executive" | "admin";
  tenant?: string;
}

export interface AuthSession {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
  user: SahajUser;
}

export interface AuthConfig {
  google_client_id: string | null;
  dev_login: boolean;
  api_base_url: string;
  google_authorized_origin: string | null;
  google_redirect_uri: null;
}

export interface SupportedLanguage {
  code: string;
  name: string;
  speech_output: boolean;
  speech_output_borrowed: boolean;
}

export interface ReadyResponse {
  status: "ready";
  storage: "ok" | "down" | "not configured";
  knowledge_base: { ok: boolean; clauses: number; domains?: Record<string, number>; problem?: string };
  features: { google_sign_in: boolean; web_search: boolean; financial_providers: FinancialProvider[] };
}

export interface ChatMessage {
  type: "text";
  text: string;
  language?: string;
  speak?: boolean;
}

export interface AssistantEvent {
  type: "assistant";
  agent: "insurance" | "loan" | "general";
  text: string;
  trace_id: string;
  citations: { id: string; text: string }[];
  structured: {
    kind: "answer" | "ask" | "confirm" | "recommendation" | "compare" | "command";
    summary: string;
    points: { text: string; sources: string[] }[];
    sources: { id: string; text: string }[];
    notes: string[];
  };
  verification: { level: "verified" | "engine" | "checked" | "blocked"; sources: number; from_cache: boolean; checks: string[] };
  suggestions: string[];
}

export type ChatEvent = { type: string; [key: string]: unknown } | AssistantEvent;

export interface UsageSummary {
  period: { start: string; resets_at: string };
  budget_usd: number;
  spent_usd: number;
  remaining_usd: number;
  percent_used: number | null;
  enforced: boolean;
  model_calls: number;
  tokens: { input: number; output: number; cached_input: number };
  calls_by_kind: Record<string, number>;
  units_by_kind: Record<string, number>;
  by_provider: Record<string, number>;
  by_kind: Record<string, number>;
  by_purpose: Record<string, number>;
  by_channel: Record<string, number>;
  estimate: true;
}

export interface InsuranceSearchResult {
  type: "web" | "news";
  title: string;
  url: string;
  description: string;
  content: string;
}

export interface InsuranceSearchResponse {
  query: string;
  provider: "firecrawl";
  results_count: number;
  credits_used: number | null;
  results: InsuranceSearchResult[];
}

export interface WebSearchResponse extends InsuranceSearchResponse {
  query: string;
}

export interface FinancialProvider {
  id: string;
  capabilities: ("credit_check" | "loan_offers" | "loan_apply" | "insurance_quotes" | "insurance_purchase")[];
}

export interface ConfirmedAction {
  provider: string;
  consent_version: string;
  confirmed: true;
}

export interface CreditCheckResult {
  id: string;
  provider: string;
  bureau: string;
  score: number | null;
  score_status: "scored" | "NA" | "NH" | "unavailable";
  checked_at?: string;
  approval_note: string;
}

export interface FinancialEvent {
  id: string;
  kind: "credit_check" | "loan_application" | "insurance_application";
  provider: string;
  status: string;
  created_at: string;
}

export interface CreditCheckInput extends ConfirmedAction {
  identity: { name: string; pan: string; date_of_birth: string; mobile: string };
}

export interface LoanOffersInput extends ConfirmedAction {
  credit_check_id: string;
  amount_inr: number;
  tenure_months: number;
  purpose: string;
}

export interface ApplicationResult {
  id: string;
  provider: string;
  status: string;
  message: string;
  checkout_url?: string | null;
}

export interface SahajClientOptions {
  baseUrl: string;
  tenantId?: string;
  accessToken?: string;
  fetch?: typeof fetch;
}

export class SahajApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "SahajApiError";
  }
}

export class SahajClient {
  readonly baseUrl: string;
  private readonly tenantId?: string;
  private readonly fetcher: typeof fetch;
  private accessToken?: string;
  private refreshToken?: string;

  constructor(options: SahajClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.tenantId = options.tenantId;
    this.accessToken = options.accessToken;
    this.fetcher = options.fetch ?? fetch;
  }

  setAccessToken(token?: string): void {
    this.accessToken = token;
  }

  async authConfig(): Promise<AuthConfig> {
    return this.request("/auth/config", { auth: false });
  }

  async ready(): Promise<ReadyResponse> {
    return this.request("/ready", { auth: false });
  }

  async languages(): Promise<{ items: SupportedLanguage[] }> {
    return this.request("/languages", { auth: false });
  }

  async signInWithGoogle(idToken: string, platform: Platform = "web"): Promise<AuthSession> {
    const session = await this.request<AuthSession>("/auth/google", {
      method: "POST", auth: false, body: { id_token: idToken, platform },
    });
    this.acceptSession(session);
    return session;
  }

  async refresh(): Promise<AuthSession> {
    if (!this.refreshToken) throw new Error("No refresh token is available.");
    const session = await this.request<AuthSession>("/auth/refresh", {
      method: "POST", auth: false, body: { refresh_token: this.refreshToken },
    });
    this.acceptSession(session);
    return session;
  }

  async logout(): Promise<void> {
    if (this.refreshToken) {
      await this.request<void>("/auth/logout", { method: "POST", auth: false, body: { refresh_token: this.refreshToken } });
    }
    this.accessToken = undefined;
    this.refreshToken = undefined;
  }

  async me(): Promise<SahajUser & { memory_consent: boolean }> {
    return this.request("/users/me");
  }

  async updateProfile(fields: { name?: string; language?: string; platform?: Platform }): Promise<SahajUser> {
    return this.request("/users/me", { method: "PATCH", body: fields });
  }

  async usage(): Promise<UsageSummary> {
    return this.request("/users/me/usage");
  }

  async searchInsurance(query: string, limit?: number): Promise<InsuranceSearchResponse> {
    return this.request("/search/insurance", { method: "POST", body: { query, ...(limit ? { limit } : {}) } });
  }

  async searchWeb(query: string, domain: "insurance" | "loan", limit?: number): Promise<WebSearchResponse> {
    return this.request("/search/web", { method: "POST", body: { query, domain, ...(limit ? { limit } : {}) } });
  }

  async financialProviders(): Promise<{ items: FinancialProvider[] }> {
    return this.request("/financial/providers");
  }

  async checkCredit(input: CreditCheckInput): Promise<CreditCheckResult> {
    return this.request("/financial/credit-check", { method: "POST", body: input });
  }

  async loanOffers(input: LoanOffersInput): Promise<{ provider: string; offers: unknown[]; count: number; disclaimer: string }> {
    return this.request("/financial/loan/offers", { method: "POST", body: input });
  }

  async applyForLoan(input: ConfirmedAction & { offer_id: string; kfs_version: string; kfs_accepted: true;
    applicant: Record<string, string | number | boolean> }): Promise<ApplicationResult> {
    return this.request("/financial/loan/apply", { method: "POST", body: input });
  }

  async insuranceQuotes(input: ConfirmedAction & { product_id: string;
    applicant: Record<string, string | number | boolean> }): Promise<{ provider: string; quotes: unknown[]; count: number; disclaimer: string }> {
    return this.request("/financial/insurance/quotes", { method: "POST", body: input });
  }

  async purchaseInsurance(input: ConfirmedAction & { quote_id: string; terms_version: string }): Promise<ApplicationResult> {
    return this.request("/financial/insurance/purchase", { method: "POST", body: input });
  }

  async financialEvents(): Promise<{ items: FinancialEvent[] }> {
    return this.request("/financial/events");
  }

  async *chat(message: ChatMessage, sessionId?: string, signal?: AbortSignal): AsyncGenerator<ChatEvent> {
    const response = await this.fetcher(`${this.baseUrl}/chat/stream`, {
      method: "POST",
      headers: this.headers(true),
      body: JSON.stringify({ session_id: sessionId, message }),
      signal,
    });
    if (!response.ok) throw await this.apiError(response);
    if (!response.body) throw new Error("The chat stream has no response body.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let pending = "";
    try {
      while (true) {
        const { value, done } = await reader.read();
        pending += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
        let split: number;
        while ((split = pending.indexOf("\n\n")) >= 0) {
          const block = pending.slice(0, split);
          pending = pending.slice(split + 2);
          const data = block.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
          if (data) yield JSON.parse(data) as ChatEvent;
        }
        if (done) break;
      }
    } finally {
      reader.releaseLock();
    }
  }

  async endChat(sessionId: string): Promise<void> {
    await this.request<void>(`/chat/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
  }

  private acceptSession(session: AuthSession): void {
    this.accessToken = session.access_token;
    this.refreshToken = session.refresh_token;
  }

  private headers(auth: boolean): HeadersInit {
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (auth && this.accessToken) headers.authorization = `Bearer ${this.accessToken}`;
    if (this.tenantId) headers["X-Tenant-ID"] = this.tenantId;
    return headers;
  }

  private async request<T>(path: string, options: { method?: string; body?: unknown; auth?: boolean } = {}): Promise<T> {
    const response = await this.fetcher(`${this.baseUrl}${path}`, {
      method: options.method ?? "GET",
      headers: this.headers(options.auth !== false),
      ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
    });
    if (!response.ok) throw await this.apiError(response);
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }

  private async apiError(response: Response): Promise<SahajApiError> {
    const body = await response.json().catch(() => ({})) as { detail?: unknown };
    const message = typeof body.detail === "string" ? body.detail : response.statusText || "Request failed.";
    return new SahajApiError(message, response.status);
  }
}

export type SahajPluginKind = "tool" | "search" | "workflow" | "data-source" | "lender" | "insurer" | "credit-bureau";
export interface JsonSchema {
  type?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  enum?: (string | number | boolean | null)[];
  description?: string;
  [key: string]: unknown;
}

export interface SahajTool<Input = unknown, Output = unknown> {
  name: string;
  description: string;
  inputSchema: JsonSchema;
  execute(input: Input, context: { client: SahajClient; tenantId?: string }): Promise<Output> | Output;
}

export interface SahajPluginContext {
  client: SahajClient;
  registerTool(tool: SahajTool): void;
}

export interface SahajPlugin {
  name: string;
  version: string;
  kind: SahajPluginKind;
  setup(context: SahajPluginContext): void | Promise<void>;
}

export class SahajPluginRegistry {
  private readonly plugins = new Map<string, SahajPlugin>();
  private readonly tools = new Map<string, SahajTool>();

  async register(plugin: SahajPlugin, client: SahajClient): Promise<void> {
    if (!plugin.name.trim() || this.plugins.has(plugin.name)) throw new Error(`Plugin already registered or unnamed: ${plugin.name}`);
    this.plugins.set(plugin.name, plugin);
    const registeredTools: string[] = [];
    try {
      await plugin.setup({
        client,
        registerTool: (tool) => {
          if (!tool.name.trim() || this.tools.has(tool.name)) throw new Error(`Tool already registered or unnamed: ${tool.name}`);
          this.tools.set(tool.name, tool);
          registeredTools.push(tool.name);
        },
      });
    } catch (error) {
      this.plugins.delete(plugin.name);
      for (const name of registeredTools) this.tools.delete(name);
      throw error;
    }
  }

  list(): { name: string; version: string; kind: SahajPluginKind }[] {
    return [...this.plugins.values()].map(({ name, version, kind }) => ({ name, version, kind }));
  }

  async execute<Input, Output>(name: string, input: Input, client: SahajClient, tenantId?: string): Promise<Output> {
    const tool = this.tools.get(name);
    if (!tool) throw new Error(`No plugin tool is registered as ${name}.`);
    return (await tool.execute(input, { client, tenantId })) as Output;
  }
}
