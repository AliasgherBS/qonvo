/**
 * Connections client: the WhatsApp session status surface (teardown W1/W2).
 *
 * A separate module rather than more of `lib/api.ts`, which that file's own
 * header asks for: it is past a thousand lines and is the file every concurrent
 * change collides in. What is already there stays there -- `sessions.qrBlob` is
 * still imported from it -- and only the newly added endpoints live here.
 */

import { apiFetch, type CallOpts, type SessionStatus } from "@/lib/api";

/** Wire shape of the enriched session row (snake_case, as the API sends it). */
interface SessionDto {
  id: string;
  session_name: string;
  label: string | null;
  status: SessionStatus;
  engine: string;
  daily_cap: number;
  warmup_stage: number;
  phone_number: string | null;
  connected_at: string | null;
  last_event_at: string | null;
}

/** Wire shape of `GET /api/sessions/{name}/status`. */
interface SessionLiveDto {
  session_name: string;
  status: SessionStatus;
  label: string | null;
  phone_number: string | null;
  connected_at: string | null;
  last_event_at: string | null;
}

export interface WhatsappSession {
  id: string;
  name: string;
  label: string | null;
  status: SessionStatus;
  /** The linked number, digits only. Null until WhatsApp has reported it. */
  phoneNumber: string | null;
  connectedAt: string | null;
  /** Newest conversation activity on this number, or null if it has seen none. */
  lastEventAt: string | null;
}

/** The live poll returns no id, so it is a partial view of the same thing. */
export type WhatsappSessionLive = Omit<WhatsappSession, "id">;

function mapSession(dto: SessionDto): WhatsappSession {
  return {
    id: dto.id,
    name: dto.session_name,
    label: dto.label,
    status: dto.status,
    phoneNumber: dto.phone_number,
    connectedAt: dto.connected_at,
    lastEventAt: dto.last_event_at,
  };
}

export const connections = {
  /** Every WhatsApp session this tenant has, with last-known status. */
  list: (opts: CallOpts = {}) =>
    apiFetch<SessionDto[]>("/api/sessions", opts).then((rows) => rows.map(mapSession)),

  /**
   * Live state for one session plus the fields the status page renders, so a
   * poll does not need a second call to the list endpoint.
   */
  live: (name: string, opts: CallOpts = {}) =>
    apiFetch<SessionLiveDto>(`/api/sessions/${encodeURIComponent(name)}/status`, opts).then(
      (dto): WhatsappSessionLive => ({
        name: dto.session_name,
        label: dto.label,
        status: dto.status,
        phoneNumber: dto.phone_number,
        connectedAt: dto.connected_at,
        lastEventAt: dto.last_event_at,
      }),
    ),

  /**
   * Link a number. `label` is optional and is what a human would call this
   * number ("Front desk"); the WAHA session key is derived server-side, which
   * is why the form no longer asks anybody to invent one (teardown W2).
   */
  create: (label: string | undefined, opts: CallOpts = {}) =>
    apiFetch<SessionDto>("/api/sessions", {
      method: "POST",
      body: { label: label?.trim() || undefined },
      ...opts,
    }).then(mapSession),

  /** Recovery: stop then start. Reuses the stored pairing, so no QR scan. */
  restart: (name: string, opts: CallOpts = {}) =>
    apiFetch<{ session_name: string; status: SessionStatus }>(
      `/api/sessions/${encodeURIComponent(name)}/restart`,
      { method: "POST", ...opts },
    ),

  /** Unlink the phone. The session is kept, so re-linking scans into it. */
  logout: (name: string, opts: CallOpts = {}) =>
    apiFetch<{ session_name: string; status: SessionStatus }>(
      `/api/sessions/${encodeURIComponent(name)}/logout`,
      { method: "POST", ...opts },
    ),
};

// ---------------------------------------------------------------------------
// Integration usage (teardown N3)
// ---------------------------------------------------------------------------

interface IntegrationUsageDto {
  last_at: string | null;
  month_count: number;
  /** Singular noun for the thing counted: "booking", "row". */
  unit: string;
}

export interface IntegrationUsage {
  lastAt: string | null;
  monthCount: number;
  unit: string;
}

/**
 * Provider -> usage, read from the same `GET /api/integrations` the page
 * already calls.
 *
 * A second request rather than a field on `integrations.list`, because
 * `lib/api.ts` is shared with several concurrent changes this cycle and its
 * `mapIntegration` drops any key it does not name. This collapses into that
 * mapper the moment it can be touched; the response is a couple of hundred
 * bytes, so the duplicate GET costs nothing measurable.
 */
export const integrationUsage = {
  map: (opts: CallOpts = {}) =>
    apiFetch<{ provider: string; usage: IntegrationUsageDto | null }[]>(
      "/api/integrations",
      opts,
    ).then((rows) => {
      const out: Record<string, IntegrationUsage> = {};
      for (const row of rows) {
        if (!row.usage) continue;
        out[row.provider] = {
          lastAt: row.usage.last_at,
          monthCount: row.usage.month_count,
          unit: row.usage.unit,
        };
      }
      return out;
    }),
};
