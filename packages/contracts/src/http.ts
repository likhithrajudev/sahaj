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
export type Role = "user" | "executive" | "admin";

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

// ---------- Files ----------

export interface StoredFile {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  created_at: string;
  /** none: not read; indexing; ready: questions can be asked about it; empty: nothing readable; unsupported: a kind
   *  that cannot be read (WebP, GIF, audio...); over_budget: the monthly limit is used up; failed. PDFs and photos are
   *  read (scans and photos by Sarvam OCR), only with the document_analysis consent. */
  index_status: "none" | "indexing" | "ready" | "empty" | "unsupported" | "over_budget" | "failed";
  indexed_chunks: number;
  category: string;
}

export interface EmiCalculationRequest {
  principal: number;
  annual_rate_percent: number;
  tenure_months: number;
}

export interface EmiCalculationResponse {
  kind: "emi";
  currency: "INR";
  method: "reducing_balance";
  inputs: EmiCalculationRequest;
  result: { emi: number; total_payment: number; total_interest: number };
  disclaimer: string;
}

export interface PrepaymentCalculationRequest extends EmiCalculationRequest {
  prepay_amount: number;
  mode?: "reduce_tenure" | "reduce_emi";
}

export interface PrepaymentCalculationResponse {
  kind: "prepayment";
  currency: "INR";
  method: "reducing_balance";
  inputs: PrepaymentCalculationRequest & { mode: "reduce_tenure" | "reduce_emi" };
  result: { emi_before: number; emi_after: number; months_before: number; months_after: number;
    months_saved: number; interest_before: number; interest_after: number; interest_saved: number };
  disclaimer: string;
}

export interface CreditCardInventoryInput {
  label: string;
  last_four?: string;
  outstanding_balance: number;
  minimum_due?: number;
  due_day?: number;
  annual_interest_rate_percent?: number;
}

export interface LoanInventoryInput {
  label: string;
  monthly_emi: number;
  outstanding_principal: number;
  due_day?: number;
  annual_interest_rate_percent?: number;
  remaining_months?: number;
}

export interface FinancialInventoryItem {
  id: string;
  type: "credit_card" | "loan";
  label: string;
  details: Omit<CreditCardInventoryInput, "label"> | Omit<LoanInventoryInput, "label">;
  created_at: string;
  updated_at: string;
}

export interface FinancialInventoryResponse {
  consent: boolean;
  consent_text: { purpose: "financial_profile"; title: string; version: string; text: string; withdrawal: string };
  items: FinancialInventoryItem[];
}

export interface ReplaceFinancialInventoryRequest {
  credit_cards: CreditCardInventoryInput[];
  loans: LoanInventoryInput[];
  confirmed: true;
}

export interface ReplaceFinancialInventoryResponse {
  items: FinancialInventoryItem[];
}

/** GET /files */
export interface FilesResponse {
  consent: boolean;
  /** Show `consent_text.text` verbatim before asking for consent. */
  consent_text: { purpose: "documents"; version: string; text: string };
  /** Consent to read PDFs so questions can be asked about them (separate from storing them). */
  analysis_consent: boolean;
  analysis_consent_text: { purpose: "document_analysis"; version: string; text: string };
  limits: { max_bytes: number; max_files: number; types: string[] };
  items: StoredFile[];
}

/** PUT /files/consent. Withdrawing deletes every stored file. */
export interface FilesConsentResponse {
  consent: boolean;
  deleted: number;
}

/** PUT /files/analysis/consent. Granting reads the PDFs already stored (`queued`); withdrawing forgets what was learned. */
export interface AnalysisConsentResponse {
  consent: boolean;
  queued?: number;
  forgotten?: number;
}

/** POST /feedback (204). One rating per person per reply; rating again replaces it. */
export interface FeedbackRequest {
  trace_id: string;
  rating: "up" | "down";
  comment?: string;
}

/** GET /ready */
export interface ReadyResponse {
  status: "ready";
  storage: "ok" | "down" | "not configured";
  knowledge_base: { ok: boolean; clauses: number; domains?: Record<string, number>; problem?: string };
  features: { google_sign_in: boolean; web_search: boolean; insurance_web_search: boolean; financial_providers: FinancialProviderCapability[] };
}

export interface FinancialProviderCapability {
  id: string;
  capabilities: ("credit_check" | "loan_offers" | "loan_apply" | "insurance_quotes" | "insurance_purchase")[];
}

export interface FinancialEvent {
  id: string;
  kind: "credit_check" | "loan_application" | "insurance_application";
  provider: string;
  status: string;
  created_at: string;
}

export interface LanguagesResponse {
  items: SupportedLanguage[];
}

/** GET /auth/config: what a client needs to start sign-in. */
export interface AuthConfig {
  google_client_id: string | null;
  /** True only for a local developer: POST /auth/dev {email} then signs in without Google. */
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

export interface InsuranceSearchRequest {
  query: string;
  limit?: number;
}

export interface InsuranceSearchResponse {
  query: string;
  provider: "firecrawl";
  results_count: number;
  credits_used: number | null;
  results: { type: "web" | "news"; title: string; url: string; description: string; content: string }[];
}

// ---------- Consent ----------

export type ConsentPurposeName = import("./voice").ConsentPurpose | "video_kyc";

export interface ConsentItem {
  purpose: ConsentPurposeName;
  title: string;
  /** Show verbatim. */
  text: string;
  version: string;
  required: boolean;
  requires: ConsentPurposeName | null;
  /** What withdrawing does, for the confirm dialog. */
  withdrawal: string;
  granted: boolean;
  granted_at: number | null;
  expires_at: number | null;
  granted_version: string | null;
  /** ask: never decided or withdrawn. renew: expired or the text changed. none: nothing to do. */
  action: "ask" | "renew" | "none";
}

/** GET /consents */
export interface ConsentsResponse {
  items: ConsentItem[];
  /** Purposes that must be granted before Sahaj can be used. */
  missing_required: ConsentPurposeName[];
}

/** PUT /consents/{purpose}. `version` is required when granting. */
export interface ConsentDecision {
  granted: boolean;
  version?: string;
}

export interface ConsentDecisionResponse {
  purpose: ConsentPurposeName;
  granted: boolean;
  /** Every purpose that went off, including ones that depended on this one. */
  withdrawn: ConsentPurposeName[];
  /** What was erased, e.g. { files: 2 }. */
  erased: Record<string, number>;
  item: ConsentItem;
}

/** The 409/500 `detail` of a refused decision. `current` is the up-to-date text when code is stale_version. */
export interface ConsentError {
  code: "stale_version" | "requires" | "unknown_purpose" | "version_required" | "erasure_failed";
  message: string;
  current?: ConsentItem;
}

/** GET /consents/history */
export interface ConsentRecord {
  purpose: ConsentPurposeName;
  event: "granted" | "revoked";
  version: string;
  text_sha256: string;
  /** True when the client echoed the version it showed. */
  version_confirmed: boolean | null;
  channel: string;
  request_id: string | null;
  expires_at: number | null;
  recorded_at: number;
  ledger_hash: string;
}

/** GET /users/me/usage. All amounts are estimated USD from configured prices. */
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
  by_kind: Record<"llm" | "stt" | "tts" | "embedding" | "ocr" | "websearch", number>;
  by_purpose: Record<string, number>;
  by_channel: Record<string, number>;
  estimate: true;
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
  insuranceSearch: "/search/insurance",
  languages: "/languages",
  consents: "/consents",
  consentsHistory: "/consents/history",
  files: "/files",
  file: "/files/{id}",
  filesAnalysisConsent: "/files/analysis/consent",
  emiCalculator: "/calculators/emi",
  prepaymentCalculator: "/calculators/prepayment",
  financialProviders: "/financial/providers",
  creditCheck: "/financial/credit-check",
  loanOffers: "/financial/loan/offers",
  loanApply: "/financial/loan/apply",
  insuranceQuotes: "/financial/insurance/quotes",
  insurancePurchase: "/financial/insurance/purchase",
  feedback: "/feedback",
  ready: "/ready",
  usage: "/users/me/usage",
  financialInventory: "/financial/inventory",
  adminUsage: "/admin/usage",
  cases: "/cases",
  deskVideoKyc: "/desk/cases/{id}/video-kyc",
  deskQueue: "/desk/queue",
  deskSocket: "/ws/desk",
  authConfig: "/auth/config",
  export: "/users/me/export",
  filesConsent: "/files/consent",
} as const;
