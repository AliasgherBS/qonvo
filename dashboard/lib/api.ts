/**
 * Typed fetch client for the Qonvo FastAPI backend.
 *
 * Route shapes follow DESIGN.md (§5 pipeline, §8 auth, §9 ops console,
 * §10 owner dashboard, §11 data model). The backend endpoints mostly don't
 * exist yet (Phase 1+) — these stubs exist so the dashboard's data-fetching
 * code, types, and UI states are ready the moment the backend lands.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
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
    const message = await res.text().catch(() => "");
    throw new ApiError(message || res.statusText, res.status);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return (await res.json()) as T;
}

/** Shared per-call options — every endpoint accepts an optional bearer token. */
export interface CallOpts {
  token?: string;
  signal?: AbortSignal;
}

// ---------------------------------------------------------------------------
// Auth (§8)
// ---------------------------------------------------------------------------

export type Role = "owner" | "staff" | "qonvo_admin";

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  tenantId: string;
  tenantName: string;
  role: Role;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  accessToken: string;
  user: AuthUser;
}

export const auth = {
  login: (payload: LoginRequest, opts: CallOpts = {}) =>
    apiFetch<LoginResponse>("/api/auth/login", {
      method: "POST",
      body: payload,
      signal: opts.signal,
    }),
};

// ---------------------------------------------------------------------------
// WhatsApp sessions (§1, §10 onboarding QR flow, §11 whatsapp_sessions)
// ---------------------------------------------------------------------------

export type SessionStatus = "STOPPED" | "STARTING" | "SCAN_QR_CODE" | "WORKING" | "FAILED";

export interface WhatsappSession {
  name: string;
  tenantId: string;
  label: string;
  status: SessionStatus;
  engine: "WEBJS" | "NOWEB";
  dailyCap: number;
  warmupStage: number;
  updatedAt: string;
}

export const sessions = {
  list: (opts: CallOpts = {}) => apiFetch<WhatsappSession[]>("/api/sessions", opts),

  get: (name: string, opts: CallOpts = {}) => apiFetch<WhatsappSession>(`/api/sessions/${name}`, opts),

  create: (payload: { name: string; label: string }, opts: CallOpts = {}) =>
    apiFetch<WhatsappSession>("/api/sessions", { method: "POST", body: payload, ...opts }),

  start: (name: string, opts: CallOpts = {}) =>
    apiFetch<WhatsappSession>(`/api/sessions/${name}/start`, { method: "POST", ...opts }),

  restart: (name: string, opts: CallOpts = {}) =>
    apiFetch<WhatsappSession>(`/api/sessions/${name}/restart`, { method: "POST", ...opts }),

  /** GET /api/{session}/auth/qr — returns a PNG; render directly as an <img> src. */
  qrImageUrl: (name: string) => `${API_BASE_URL}/api/${name}/auth/qr`,
};

// ---------------------------------------------------------------------------
// Conversations & inbox (§5.5 takeover state machine, §11 conversations/messages)
// ---------------------------------------------------------------------------

export type ConversationState = "bot_active" | "paused_by_agent" | "paused_by_owner" | "needs_human";

export interface Conversation {
  id: string;
  tenantId: string;
  customerName: string | null;
  customerNumber: string;
  state: ConversationState;
  lastMessagePreview: string | null;
  lastActivityAt: string;
  unreadCount: number;
}

export type MessageDirection = "inbound" | "outbound";
export type MessageAuthor = "bot" | "human" | "customer";
export type MessageType = "text" | "voice" | "image" | "file";

export interface Message {
  id: string;
  conversationId: string;
  direction: MessageDirection;
  author: MessageAuthor;
  type: MessageType;
  text: string | null;
  mediaUrl: string | null;
  createdAt: string;
}

export const conversations = {
  list: (opts: CallOpts = {}) => apiFetch<Conversation[]>("/api/conversations", opts),

  get: (id: string, opts: CallOpts = {}) => apiFetch<Conversation>(`/api/conversations/${id}`, opts),

  messages: (id: string, opts: CallOpts = {}) =>
    apiFetch<Message[]>(`/api/conversations/${id}/messages`, opts),

  sendMessage: (id: string, text: string, opts: CallOpts = {}) =>
    apiFetch<Message>(`/api/conversations/${id}/messages`, { method: "POST", body: { text }, ...opts }),

  /** Owner/staff clicks "take over" in the inbox → paused_by_owner (§5.5). */
  takeover: (id: string, opts: CallOpts = {}) =>
    apiFetch<Conversation>(`/api/conversations/${id}/takeover`, { method: "POST", ...opts }),

  /** Resume bot replies for this conversation. */
  release: (id: string, opts: CallOpts = {}) =>
    apiFetch<Conversation>(`/api/conversations/${id}/release`, { method: "POST", ...opts }),
};

// ---------------------------------------------------------------------------
// Knowledge base (§6 RAG ingestion)
// ---------------------------------------------------------------------------

export type KnowledgeSourceType = "file" | "website" | "manual";
export type KnowledgeSourceStatus = "pending" | "processing" | "ready" | "error";

export interface KnowledgeSource {
  id: string;
  type: KnowledgeSourceType;
  title: string;
  url: string | null;
  autoRefresh: boolean;
  cron: string | null;
  status: KnowledgeSourceStatus;
  chunkCount: number;
  updatedAt: string;
}

export const knowledge = {
  listSources: (opts: CallOpts = {}) => apiFetch<KnowledgeSource[]>("/api/knowledge/sources", opts),

  addWebsite: (payload: { url: string; autoRefresh: boolean }, opts: CallOpts = {}) =>
    apiFetch<KnowledgeSource>("/api/knowledge/sources", {
      method: "POST",
      body: { type: "website", ...payload },
      ...opts,
    }),

  uploadFile: (file: File, opts: CallOpts = {}) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<KnowledgeSource>("/api/knowledge/sources/upload", {
      method: "POST",
      body: form,
      ...opts,
    });
  },

  deleteSource: (id: string, opts: CallOpts = {}) =>
    apiFetch<void>(`/api/knowledge/sources/${id}`, { method: "DELETE", ...opts }),
};

// ---------------------------------------------------------------------------
// Notifications (§5.5 escalation log, §12.1 disconnect alerts)
// ---------------------------------------------------------------------------

export type NotificationType = "escalation" | "disconnect" | "quota_warning" | "quota_exceeded" | "other";

export interface Notification {
  id: string;
  type: NotificationType;
  message: string;
  read: boolean;
  createdAt: string;
}

export const notifications = {
  list: (opts: CallOpts = {}) => apiFetch<Notification[]>("/api/notifications", opts),

  markRead: (id: string, opts: CallOpts = {}) =>
    apiFetch<void>(`/api/notifications/${id}/read`, { method: "POST", ...opts }),
};

// ---------------------------------------------------------------------------
// Settings / tenant config (§10 settings, §11 tenant_config)
// ---------------------------------------------------------------------------

export interface BusinessHours {
  timezone: string;
  windows: { day: number; start: string; end: string }[];
}

export interface TenantConfig {
  persona: string;
  tone: string;
  languages: string[];
  businessHours: BusinessHours;
  escalationNumber: string;
  autoResumeHours: number;
}

export const settings = {
  get: (opts: CallOpts = {}) => apiFetch<TenantConfig>("/api/settings", opts),

  update: (payload: Partial<TenantConfig>, opts: CallOpts = {}) =>
    apiFetch<TenantConfig>("/api/settings", { method: "PATCH", body: payload, ...opts }),
};

// ---------------------------------------------------------------------------
// Analytics (§10 analytics)
// ---------------------------------------------------------------------------

export interface AnalyticsSummary {
  messagesIn: number;
  messagesOut: number;
  avgResponseTimeSeconds: number;
  resolutionRate: number;
  handoffRate: number;
  leadsCount: number;
  bookingsCount: number;
  topUnansweredQuestions: string[];
}

export const analytics = {
  summary: (opts: CallOpts = {}) => apiFetch<AnalyticsSummary>("/api/analytics/summary", opts),
};

// ---------------------------------------------------------------------------
// Ops console — qonvo_admin only (§9)
// ---------------------------------------------------------------------------

export type TenantStatus = "onboarding" | "active" | "suspended";

export interface AdminTenant {
  id: string;
  name: string;
  status: TenantStatus;
  ownerEmail: string;
  createdAt: string;
}

export const adminTenants = {
  list: (opts: CallOpts = {}) => apiFetch<AdminTenant[]>("/api/admin/tenants", opts),

  create: (payload: { name: string; ownerEmail: string }, opts: CallOpts = {}) =>
    apiFetch<AdminTenant>("/api/admin/tenants", { method: "POST", body: payload, ...opts }),

  suspend: (id: string, opts: CallOpts = {}) =>
    apiFetch<AdminTenant>(`/api/admin/tenants/${id}/suspend`, { method: "POST", ...opts }),
};

export interface FleetSession extends WhatsappSession {
  tenantName: string;
  webhookFailureCount: number;
}

export const adminFleet = {
  sessions: (opts: CallOpts = {}) => apiFetch<FleetSession[]>("/api/admin/fleet/sessions", opts),

  restart: (name: string, opts: CallOpts = {}) =>
    apiFetch<FleetSession>(`/api/admin/fleet/sessions/${name}/restart`, { method: "POST", ...opts }),
};
