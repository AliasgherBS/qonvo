/**
 * Typed fetch client for the Qonvo FastAPI backend.
 *
 * Route shapes follow the Phase 1C backend contract (DESIGN.md §5 pipeline,
 * §8 auth, §9 ops console, §10 owner dashboard, §11 data model). The backend
 * returns snake_case JSON — the `*Dto` interfaces below mirror the wire
 * shape exactly; every exported function maps that into a camelCase shape
 * for the rest of the app to consume.
 */

// Server-side code (Auth.js authorize, SSR) talks to the backend directly over
// the internal network; the browser uses NEXT_PUBLIC_API_URL, which in a public
// (tunnelled) deploy is a relative path like "/backend" that a Next.js rewrite
// proxies to the API — so we never have to bake the public URL into the bundle.
const API_BASE_URL =
  typeof window === "undefined"
    ? process.env.INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
    : process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * Turn any thrown value from a request into an honest, human-readable message
 * that reflects the ACTUAL failure — never a "backend isn't connected"
 * placeholder. Prefers the backend's error detail for client errors, and a
 * clear generic for network/server failures.
 */
export function describeError(err: unknown, fallback = "Something went wrong. Please try again."): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return "Your session expired — please sign in again.";
    if (err.status === 403) return err.message || "You don't have permission to do that.";
    if (err.status === 404) return err.message || "Not found.";
    if (err.status === 429) return err.message || "Too many requests — please wait a moment.";
    if (err.status >= 500) return `Server error (${err.status}) — please try again in a moment.`;
    // 400 / 409 / 422 etc. — the backend's detail is the real, useful message.
    return err.message || fallback;
  }
  // fetch() itself rejected (no response) — DNS, offline, CORS, tunnel down.
  if (err instanceof TypeError) return "Couldn't reach the server — check your connection and try again.";
  return err instanceof Error && err.message ? err.message : fallback;
}

interface ApiFetchInit extends Omit<RequestInit, "body"> {
  token?: string;
  body?: BodyInit | object | null;
}

async function apiFetch<T>(path: string, init: ApiFetchInit = {}): Promise<T> {
  const { token, headers, body, ...rest } = init;
  const isPlainObject =
    body != null && typeof body === "object" && !(body instanceof FormData) && !(body instanceof Blob);

  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    body: isPlainObject ? JSON.stringify(body) : (body as BodyInit | null | undefined),
    headers: {
      ...(isPlainObject ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
  });

  if (!res.ok) {
    const raw = await res.text().catch(() => "");
    let message = raw || res.statusText;
    // FastAPI errors are {"detail": "..."} or a validation array — extract the
    // real detail so callers can show what actually went wrong.
    try {
      const parsed = JSON.parse(raw) as { detail?: unknown };
      if (typeof parsed.detail === "string") message = parsed.detail;
      else if (Array.isArray(parsed.detail)) {
        const first = parsed.detail[0] as { msg?: string } | undefined;
        if (first?.msg) message = first.msg;
      }
    } catch {
      /* body isn't JSON — keep the raw text / status text */
    }
    throw new ApiError(message, res.status);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return (await res.json()) as T;
}

function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

/** Shared per-call options — every endpoint accepts an optional bearer token. */
export interface CallOpts {
  token?: string;
  signal?: AbortSignal;
}

// ---------------------------------------------------------------------------
// Auth (§8) — POST /api/auth/login, GET /api/me
// ---------------------------------------------------------------------------

export type Role = "owner" | "staff" | "qonvo_admin";

export interface LoginRequest {
  email: string;
  password: string;
}

interface LoginResponseDto {
  access_token: string;
  token_type: string;
  role: Role;
  tenant_id: string;
  name: string;
}

export interface LoginResult {
  accessToken: string;
  tokenType: string;
  role: Role;
  tenantId: string;
  name: string;
}

interface MeDto {
  email: string;
  name: string;
  role: Role;
  tenant_id: string;
  tenant_name: string;
}

export interface Me {
  email: string;
  name: string;
  role: Role;
  tenantId: string;
  tenantName: string;
}

export interface SignupRequest {
  businessName: string;
  ownerName: string;
  email: string;
  password: string;
}

export const auth = {
  login: (payload: LoginRequest, opts: CallOpts = {}) =>
    apiFetch<LoginResponseDto>("/api/auth/login", { method: "POST", body: payload, signal: opts.signal }).then(
      (dto): LoginResult => ({
        accessToken: dto.access_token,
        tokenType: dto.token_type,
        role: dto.role,
        tenantId: dto.tenant_id,
        name: dto.name,
      }),
    ),

  signup: (payload: SignupRequest, opts: CallOpts = {}) =>
    apiFetch<LoginResponseDto>("/api/auth/signup", {
      method: "POST",
      body: {
        business_name: payload.businessName,
        owner_name: payload.ownerName,
        email: payload.email,
        password: payload.password,
      },
      signal: opts.signal,
    }).then((dto): LoginResult => ({
      accessToken: dto.access_token,
      tokenType: dto.token_type,
      role: dto.role,
      tenantId: dto.tenant_id,
      name: dto.name,
    })),

  me: (opts: CallOpts = {}) =>
    apiFetch<MeDto>("/api/me", opts).then(
      (dto): Me => ({
        email: dto.email,
        name: dto.name,
        role: dto.role,
        tenantId: dto.tenant_id,
        tenantName: dto.tenant_name,
      }),
    ),
};

// ---------------------------------------------------------------------------
// WhatsApp sessions — already live (§1, §10 onboarding QR flow)
// ---------------------------------------------------------------------------

export type SessionStatus = "STOPPED" | "STARTING" | "SCAN_QR_CODE" | "WORKING" | "FAILED";

// Both the create (SessionResponse) and status endpoints key the session by
// `session_name`; the status route also nests a `status` scalar.
interface SessionCreateDto {
  session_name: string;
  status: SessionStatus;
}

interface SessionStatusDto {
  session_name: string;
  status: SessionStatus;
}

export interface WhatsappSessionStatus {
  name: string;
  status: SessionStatus;
}

export const sessions = {
  create: (payload: { name: string; label?: string }, opts: CallOpts = {}) =>
    apiFetch<SessionCreateDto>("/api/sessions", {
      method: "POST",
      // Backend requires `session_name` (a bare `name` 422s).
      body: { session_name: payload.name, label: payload.label },
      ...opts,
    }).then((dto): WhatsappSessionStatus => ({ name: dto.session_name, status: dto.status })),

  status: (name: string, opts: CallOpts = {}) =>
    apiFetch<SessionStatusDto>(`/api/sessions/${name}/status`, opts).then(
      (dto): WhatsappSessionStatus => ({ name: dto.session_name, status: dto.status }),
    ),

  /** This tenant's sessions with last-known status — powers the connect banner. */
  list: (opts: CallOpts = {}) =>
    apiFetch<SessionStatusDto[]>("/api/sessions", opts).then((rows) =>
      rows.map((dto): WhatsappSessionStatus => ({ name: dto.session_name, status: dto.status })),
    ),

  /**
   * GET /api/sessions/{name}/qr — the QR PNG. The endpoint requires auth, and an
   * <img> tag can't send a bearer header (it would 401 and the QR never renders),
   * so fetch it as an authenticated blob and let the caller wrap it in an object
   * URL (revoking the previous one to avoid leaks).
   */
  qrBlob: async (name: string, opts: CallOpts = {}): Promise<Blob> => {
    const res = await fetch(`${API_BASE_URL}/api/sessions/${name}/qr`, {
      headers: opts.token ? { Authorization: `Bearer ${opts.token}` } : {},
      signal: opts.signal,
    });
    if (!res.ok) throw new ApiError((await res.text().catch(() => "")) || res.statusText, res.status);
    return res.blob();
  },
};

// ---------------------------------------------------------------------------
// Conversations & inbox (§5.5 takeover state machine, §11 conversations/messages)
// ---------------------------------------------------------------------------

export type ConversationState = "bot_active" | "paused_by_agent" | "paused_by_owner" | "needs_human";

interface ConversationDto {
  id: string;
  chat_id: string;
  state: ConversationState;
  last_message_preview: string | null;
  last_activity_at: string;
  unread: boolean;
}

export interface Conversation {
  id: string;
  chatId: string;
  state: ConversationState;
  lastMessagePreview: string | null;
  lastActivityAt: string;
  unread: boolean;
}

interface ConversationsListDto {
  items: ConversationDto[];
  total: number;
}

export interface ConversationsListResult {
  items: Conversation[];
  total: number;
}

function mapConversation(dto: ConversationDto): Conversation {
  return {
    id: dto.id,
    chatId: dto.chat_id,
    state: dto.state,
    lastMessagePreview: dto.last_message_preview,
    lastActivityAt: dto.last_activity_at,
    unread: dto.unread,
  };
}

export type MessageDirection = "inbound" | "outbound";
export type MessageAuthor = "bot" | "human" | "customer";
export type MessageType = "text" | "voice" | "image" | "file";

interface MessageDto {
  id: string;
  direction: MessageDirection;
  author: MessageAuthor;
  type: MessageType;
  body: string;
  created_at: string;
}

export interface Message {
  id: string;
  direction: MessageDirection;
  author: MessageAuthor;
  type: MessageType;
  body: string;
  createdAt: string;
}

interface MessagesListDto {
  items: MessageDto[];
}

function mapMessage(dto: MessageDto): Message {
  return {
    id: dto.id,
    direction: dto.direction,
    author: dto.author,
    type: dto.type,
    body: dto.body,
    createdAt: dto.created_at,
  };
}

interface StateResponseDto {
  state: ConversationState;
}

interface ReplyResponseDto {
  message_id: string;
}

export const conversations = {
  list: (params: { state?: ConversationState; limit?: number; offset?: number } = {}, opts: CallOpts = {}) =>
    apiFetch<ConversationsListDto>(`/api/conversations${buildQuery(params)}`, opts).then(
      (dto): ConversationsListResult => ({
        items: dto.items.map(mapConversation),
        total: dto.total,
      }),
    ),

  messages: (id: string, params: { limit?: number; before?: string } = {}, opts: CallOpts = {}) =>
    apiFetch<MessagesListDto>(`/api/conversations/${id}/messages${buildQuery(params)}`, opts).then((dto) => ({
      items: dto.items.map(mapMessage),
    })),

  /** Owner/staff clicks "take over" in the inbox → paused_by_owner (§5.5). */
  takeover: (id: string, opts: CallOpts = {}) =>
    apiFetch<StateResponseDto>(`/api/conversations/${id}/takeover`, { method: "POST", ...opts }),

  /** Resume bot replies for this conversation. */
  release: (id: string, opts: CallOpts = {}) =>
    apiFetch<StateResponseDto>(`/api/conversations/${id}/release`, { method: "POST", ...opts }),

  reply: (id: string, text: string, opts: CallOpts = {}) =>
    apiFetch<ReplyResponseDto>(`/api/conversations/${id}/reply`, { method: "POST", body: { text }, ...opts }).then(
      (dto) => ({ messageId: dto.message_id }),
    ),
};

// ---------------------------------------------------------------------------
// Knowledge base (§6 RAG ingestion)
// ---------------------------------------------------------------------------

export type KnowledgeSourceType = "file" | "website" | "manual" | "url";
// Backend statuses: "pending_ingest" (queued) → "ready" | "error". Kept as a
// widened string so a new backend status never renders as a broken badge.
export type KnowledgeSourceStatus = "pending_ingest" | "ready" | "error" | (string & {});

interface KnowledgeSourceDto {
  id: string;
  type: KnowledgeSourceType;
  title: string;
  url: string | null;
  content: string | null;
  status: KnowledgeSourceStatus;
  auto_refresh: boolean;
  created_at: string;
}

export interface KnowledgeSource {
  id: string;
  type: KnowledgeSourceType;
  title: string;
  url: string | null;
  content: string | null;
  status: KnowledgeSourceStatus;
  createdAt: string | null;
}

function mapKnowledgeSource(dto: KnowledgeSourceDto): KnowledgeSource {
  return {
    id: dto.id,
    type: dto.type,
    title: dto.title,
    url: dto.url,
    content: dto.content,
    status: dto.status,
    createdAt: dto.created_at ?? null,
  };
}

interface KnowledgeGapDto {
  id: string;
  question: string;
  count: number;
}

export interface KnowledgeGap {
  id: string;
  question: string;
  count: number;
}

export const knowledge = {
  listSources: (opts: CallOpts = {}) =>
    apiFetch<KnowledgeSourceDto[]>("/api/knowledge/sources", opts).then((items) => items.map(mapKnowledgeSource)),

  /** Manual entry: POST /api/knowledge/sources {type: "manual", title, content}. */
  addManualEntry: (payload: { title: string; content: string }, opts: CallOpts = {}) =>
    apiFetch<KnowledgeSourceDto>("/api/knowledge/sources", {
      method: "POST",
      body: { type: "manual", ...payload },
      ...opts,
    }).then(mapKnowledgeSource),

  /** File upload: create the source record, then upload the file to it. */
  createFileSource: (title: string, opts: CallOpts = {}) =>
    apiFetch<KnowledgeSourceDto>("/api/knowledge/sources", {
      method: "POST",
      body: { type: "file", title },
      ...opts,
    }).then(mapKnowledgeSource),

  uploadFile: (id: string, file: File, opts: CallOpts = {}) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<KnowledgeSourceDto>(`/api/knowledge/sources/${id}/upload`, {
      method: "POST",
      body: form,
      ...opts,
    }).then(mapKnowledgeSource);
  },

  getSource: (id: string, opts: CallOpts = {}) =>
    apiFetch<KnowledgeSourceDto>(`/api/knowledge/sources/${id}`, opts).then(mapKnowledgeSource),

  updateSource: (id: string, payload: { title?: string; content?: string }, opts: CallOpts = {}) =>
    apiFetch<KnowledgeSourceDto>(`/api/knowledge/sources/${id}`, {
      method: "PUT",
      body: payload,
      ...opts,
    }).then(mapKnowledgeSource),

  deleteSource: (id: string, opts: CallOpts = {}) =>
    apiFetch<void>(`/api/knowledge/sources/${id}`, { method: "DELETE", ...opts }),

  gaps: (opts: CallOpts = {}) => apiFetch<KnowledgeGapDto[]>("/api/knowledge/gaps", opts),
};

// ---------------------------------------------------------------------------
// Notifications (§5.5 escalation log, §12.1 disconnect alerts)
// ---------------------------------------------------------------------------

// Mirrors the backend NotificationType enum (app/models/enums.py). An unknown
// future value is tolerated by the UI's fallback rendering.
export type NotificationType =
  | "escalation"
  | "disconnect"
  | "quota_warning"
  | "session_failed"
  | (string & {});

interface NotificationDto {
  id: string;
  type: NotificationType;
  title: string;
  body: string | null;
  read: boolean;
  created_at: string;
}

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  body: string | null;
  // Convenience one-liner for compact UIs (the bell) — title, then body.
  message: string;
  read: boolean;
  createdAt: string;
}

function mapNotification(dto: NotificationDto): Notification {
  return {
    id: dto.id,
    type: dto.type,
    title: dto.title,
    body: dto.body,
    message: [dto.title, dto.body].filter(Boolean).join(" — "),
    read: dto.read,
    createdAt: dto.created_at,
  };
}

export const notifications = {
  list: (params: { unread?: boolean } = {}, opts: CallOpts = {}) =>
    apiFetch<NotificationDto[]>(`/api/notifications${buildQuery(params)}`, opts).then((items) =>
      items.map(mapNotification),
    ),

  markRead: (id: string, opts: CallOpts = {}) =>
    apiFetch<void>(`/api/notifications/${id}/read`, { method: "POST", ...opts }),
};

// ---------------------------------------------------------------------------
// Config / settings (§10 settings, §11 tenant_config)
// ---------------------------------------------------------------------------

export type LlmProvider = "openai" | "openrouter" | "groq" | "gemini";

export interface BusinessHoursDay {
  day: number;
  open: string;
  close: string;
  closed: boolean;
}

// Backend stores business_hours as the shape the pipeline reads (§5.2):
// { enabled, timezone, hours: { mon: [["09:00","17:00"]], ... }, closed_message }.
// The form edits a friendlier per-day array; these converters bridge the two.
// (Sending the raw array 422'd the entire config save.)
interface BusinessHoursConfig {
  enabled?: boolean;
  timezone?: string;
  hours?: Record<string, [string, string][]>;
  closed_message?: string | null;
}

const DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

function daysFromConfig(bh: BusinessHoursConfig | null | undefined): BusinessHoursDay[] {
  const hours = bh?.hours ?? {};
  const hasAny = Object.keys(hours).length > 0;
  return DAY_KEYS.map((key, day) => {
    if (!hasAny) return { day, open: "09:00", close: "17:00", closed: false };
    const windows = hours[key] ?? [];
    if (windows.length > 0) {
      const [open, close] = windows[0];
      return { day, open, close, closed: false };
    }
    return { day, open: "09:00", close: "17:00", closed: true };
  });
}

function configFromDays(
  days: BusinessHoursDay[],
  enabled: boolean,
  timezone: string,
  closedMessage: string | null,
): BusinessHoursConfig {
  const hours: Record<string, [string, string][]> = {};
  for (const d of days) {
    if (!d.closed) hours[DAY_KEYS[d.day]] = [[d.open, d.close]];
  }
  return { enabled, timezone, hours, closed_message: closedMessage || null };
}

interface TenantConfigDto {
  // The backend leaves every optional field null until it's set (a freshly
  // created tenant_config is all-null), so mirror that here and coerce to
  // safe defaults in mapTenantConfig — the form assumes strings.
  persona: string | null;
  business_name: string | null;
  primary_language: string | null;
  tone: string | null;
  custom_instructions: string | null;
  business_hours: BusinessHoursConfig | null;
  owner_alert_number: string | null;
  llm_provider: LlmProvider | null;
  llm_model: string | null;
  payment_details: string | null;
  voice_reply_mode: VoiceReplyMode | null;
}

export type VoiceReplyMode = "match" | "always" | "never";

export interface TenantConfig {
  persona: string;
  businessName: string;
  primaryLanguage: string;
  tone: string;
  customInstructions: string;
  businessHours: BusinessHoursDay[];
  businessHoursEnabled: boolean;
  businessHoursTimezone: string;
  businessHoursClosedMessage: string | null;
  ownerAlertNumber: string;
  llmProvider: LlmProvider | "";
  llmModel: string;
  paymentDetails: string;
  voiceReplyMode: VoiceReplyMode;
}

function mapTenantConfig(dto: TenantConfigDto): TenantConfig {
  const bh = dto.business_hours ?? {};
  return {
    persona: dto.persona ?? "",
    businessName: dto.business_name ?? "",
    primaryLanguage: dto.primary_language ?? "",
    tone: dto.tone ?? "",
    customInstructions: dto.custom_instructions ?? "",
    businessHours: daysFromConfig(bh),
    businessHoursEnabled: bh.enabled ?? false,
    businessHoursTimezone: bh.timezone ?? "UTC",
    businessHoursClosedMessage: bh.closed_message ?? null,
    ownerAlertNumber: dto.owner_alert_number ?? "",
    llmProvider: dto.llm_provider ?? "",
    llmModel: dto.llm_model ?? "",
    paymentDetails: dto.payment_details ?? "",
    voiceReplyMode: dto.voice_reply_mode ?? "match",
  };
}

function toTenantConfigDto(cfg: TenantConfig): TenantConfigDto {
  return {
    persona: cfg.persona,
    business_name: cfg.businessName,
    primary_language: cfg.primaryLanguage,
    tone: cfg.tone,
    custom_instructions: cfg.customInstructions,
    business_hours: configFromDays(
      cfg.businessHours,
      cfg.businessHoursEnabled,
      cfg.businessHoursTimezone,
      cfg.businessHoursClosedMessage,
    ),
    owner_alert_number: cfg.ownerAlertNumber,
    llm_provider: cfg.llmProvider || null,
    llm_model: cfg.llmModel,
    payment_details: cfg.paymentDetails || null,
    voice_reply_mode: cfg.voiceReplyMode,
  };
}

export const config = {
  get: (opts: CallOpts = {}) => apiFetch<TenantConfigDto>("/api/config", opts).then(mapTenantConfig),

  update: (payload: TenantConfig, opts: CallOpts = {}) =>
    apiFetch<TenantConfigDto>("/api/config", { method: "PUT", body: toTenantConfigDto(payload), ...opts }).then(
      mapTenantConfig,
    ),
};

// ---------------------------------------------------------------------------
// Analytics (§9 analytics dashboard, §13 metering)
// ---------------------------------------------------------------------------

interface AnalyticsSummaryDto {
  range_days: number;
  totals: Record<string, number>;
  daily: { day: string; messages_in: number; messages_out: number; cost: number; tokens: number }[];
  conversation_states: Record<string, number>;
  top_gaps: { question: string; count: number }[];
}

export interface AnalyticsDailyPoint {
  day: string;
  messagesIn: number;
  messagesOut: number;
  cost: number;
}

export interface AnalyticsSummary {
  rangeDays: number;
  totals: Record<string, number>;
  daily: AnalyticsDailyPoint[];
  conversationStates: Record<string, number>;
  topGaps: { question: string; count: number }[];
}

export const analytics = {
  summary: (params: { days?: number } = {}, opts: CallOpts = {}) =>
    apiFetch<AnalyticsSummaryDto>(`/api/analytics/summary${buildQuery(params)}`, opts).then(
      (dto): AnalyticsSummary => ({
        rangeDays: dto.range_days,
        totals: dto.totals,
        daily: dto.daily.map((d) => ({
          day: d.day,
          messagesIn: d.messages_in,
          messagesOut: d.messages_out,
          cost: d.cost,
        })),
        conversationStates: dto.conversation_states,
        topGaps: dto.top_gaps,
      }),
    ),
};

// ---------------------------------------------------------------------------
// Integrations — Google Calendar / Sheets (§7 agentic skills)
// ---------------------------------------------------------------------------

export type IntegrationProvider = "google_calendar" | "google_sheets";

interface IntegrationDto {
  provider: IntegrationProvider;
  enabled: boolean;
  config: Record<string, string>;
  has_credentials: boolean;
  has_tenant_key: boolean;
  service_account_email: string | null;
}

export interface Integration {
  provider: IntegrationProvider;
  enabled: boolean;
  config: Record<string, string>;
  hasCredentials: boolean;
  hasTenantKey: boolean;
  serviceAccountEmail: string | null;
}

function mapIntegration(dto: IntegrationDto): Integration {
  return {
    provider: dto.provider,
    enabled: dto.enabled,
    config: dto.config ?? {},
    hasCredentials: dto.has_credentials,
    hasTenantKey: dto.has_tenant_key,
    serviceAccountEmail: dto.service_account_email,
  };
}

export interface IntegrationUpdate {
  config?: Record<string, string>;
  serviceAccountJson?: string;
  enabled?: boolean;
}

export interface IntegrationTestResult {
  ok: boolean;
  message: string;
  serviceAccountEmail: string | null;
}

interface IntegrationTestResultDto {
  ok: boolean;
  message: string;
  service_account_email: string | null;
}

export const integrations = {
  list: (opts: CallOpts = {}) =>
    apiFetch<IntegrationDto[]>("/api/integrations", opts).then((items) => items.map(mapIntegration)),

  update: (provider: IntegrationProvider, payload: IntegrationUpdate, opts: CallOpts = {}) =>
    apiFetch<IntegrationDto>(`/api/integrations/${provider}`, {
      method: "PUT",
      body: {
        config: payload.config,
        service_account_json: payload.serviceAccountJson,
        enabled: payload.enabled,
      },
      ...opts,
    }).then(mapIntegration),

  disconnect: (provider: IntegrationProvider, opts: CallOpts = {}) =>
    apiFetch<void>(`/api/integrations/${provider}`, { method: "DELETE", ...opts }),

  test: (provider: IntegrationProvider, opts: CallOpts = {}) =>
    apiFetch<IntegrationTestResultDto>(`/api/integrations/${provider}/test`, { method: "POST", ...opts }).then(
      (dto): IntegrationTestResult => ({
        ok: dto.ok,
        message: dto.message,
        serviceAccountEmail: dto.service_account_email,
      }),
    ),
};

// ---------------------------------------------------------------------------
// Ops console — qonvo_admin only (§9)
// ---------------------------------------------------------------------------

export type TenantStatus = "onboarding" | "active" | "suspended";

interface AdminTenantDto {
  id: string;
  name: string;
  slug: string;
  status: TenantStatus;
  owner_email: string;
  owner_name: string;
  created_at: string;
}

export interface AdminTenant {
  id: string;
  name: string;
  slug: string;
  status: TenantStatus;
  ownerEmail: string;
  ownerName: string;
  createdAt: string;
}

function mapAdminTenant(dto: AdminTenantDto): AdminTenant {
  return {
    id: dto.id,
    name: dto.name,
    slug: dto.slug,
    status: dto.status,
    ownerEmail: dto.owner_email,
    ownerName: dto.owner_name,
    createdAt: dto.created_at,
  };
}

export interface CreateTenantRequest {
  name: string;
  slug: string;
  ownerEmail: string;
  ownerName: string;
}

interface CreateTenantResponseDto extends AdminTenantDto {
  temp_password: string;
}

export interface CreateTenantResult extends AdminTenant {
  tempPassword: string;
}

export const adminTenants = {
  list: (opts: CallOpts = {}) =>
    apiFetch<AdminTenantDto[]>("/api/admin/tenants", opts).then((items) => items.map(mapAdminTenant)),

  get: (id: string, opts: CallOpts = {}) =>
    apiFetch<AdminTenantDto>(`/api/admin/tenants/${id}`, opts).then(mapAdminTenant),

  create: (payload: CreateTenantRequest, opts: CallOpts = {}) =>
    apiFetch<CreateTenantResponseDto>("/api/admin/tenants", {
      method: "POST",
      body: {
        name: payload.name,
        slug: payload.slug,
        owner_email: payload.ownerEmail,
        owner_name: payload.ownerName,
      },
      ...opts,
    }).then((dto): CreateTenantResult => ({ ...mapAdminTenant(dto), tempPassword: dto.temp_password })),

  // Config is embedded in GET /tenants/{id} — there is no /config GET route.
  getConfig: (id: string, opts: CallOpts = {}) =>
    apiFetch<AdminTenantDto & { config: TenantConfigDto | null }>(
      `/api/admin/tenants/${id}`,
      opts,
    ).then((dto) => (dto.config ? mapTenantConfig(dto.config) : null)),

  updateConfig: (id: string, payload: TenantConfig, opts: CallOpts = {}) =>
    apiFetch<TenantConfigDto>(`/api/admin/tenants/${id}/config`, {
      method: "PUT",
      body: toTenantConfigDto(payload),
      ...opts,
    }).then(mapTenantConfig),
};

interface AdminOverviewDto {
  total_tenants: number;
  connected_tenants: number;
  total_sessions: number;
  tenants_with_knowledge: number;
  knowledge_sources_ready: number;
  messages_30d: number;
  cost_30d: number;
}

export interface AdminOverview {
  totalTenants: number;
  connectedTenants: number;
  totalSessions: number;
  tenantsWithKnowledge: number;
  knowledgeSourcesReady: number;
  messages30d: number;
  cost30d: number;
}

export const adminOverview = {
  get: (opts: CallOpts = {}) =>
    apiFetch<AdminOverviewDto>("/api/admin/overview", opts).then(
      (dto): AdminOverview => ({
        totalTenants: dto.total_tenants,
        connectedTenants: dto.connected_tenants,
        totalSessions: dto.total_sessions,
        tenantsWithKnowledge: dto.tenants_with_knowledge,
        knowledgeSourcesReady: dto.knowledge_sources_ready,
        messages30d: dto.messages_30d,
        cost30d: dto.cost_30d,
      }),
    ),
};

interface FleetSessionDto {
  session_name: string;
  tenant_id: string;
  tenant_name: string | null;
  label: string | null;
  status: SessionStatus;
  live_status: string | null;
}

export interface FleetSession {
  name: string;
  tenantId: string;
  tenantName: string | null;
  label: string | null;
  status: SessionStatus;
  liveStatus: string | null;
}

function mapFleetSession(dto: FleetSessionDto): FleetSession {
  return {
    name: dto.session_name,
    tenantId: dto.tenant_id,
    tenantName: dto.tenant_name,
    label: dto.label,
    status: dto.status,
    liveStatus: dto.live_status,
  };
}

export const adminFleet = {
  list: (opts: CallOpts = {}) =>
    apiFetch<FleetSessionDto[]>("/api/admin/fleet", opts).then((items) => items.map(mapFleetSession)),
};

interface UsageRowDto {
  tenant_id: string;
  tenant_name: string;
  month: string;
  messages: number;
  tokens: number;
  cost: number;
}

export interface UsageRow {
  tenantId: string;
  tenantName: string;
  month: string;
  messages: number;
  tokens: number;
  cost: number;
}

function mapUsageRow(dto: UsageRowDto): UsageRow {
  return {
    tenantId: dto.tenant_id,
    tenantName: dto.tenant_name,
    month: dto.month,
    messages: dto.messages,
    tokens: dto.tokens,
    cost: dto.cost,
  };
}

export const adminUsage = {
  list: (opts: CallOpts = {}) =>
    apiFetch<UsageRowDto[]>("/api/admin/usage", opts).then((items) => items.map(mapUsageRow)),
};
