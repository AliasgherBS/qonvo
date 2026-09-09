/**
 * Ops-console endpoints that existed with no interface, plus the audit reader.
 *
 * Three of the four findings behind this file are the same shape: a route that
 * works, is properly gated, and that nothing on any page ever calls.
 *
 * - `PUT /api/admin/tenants/{id}/subscription` is the manual billing adapter.
 *   It takes a catalogue key and routes it through `apply_plan`, which rewrites
 *   `tenant_config.entitlements` from `backend/app/billing/plans.py`. The
 *   console instead offered a paid/trial toggle over the coarse `tenants.plan`
 *   label, which derives nothing: a customer marked paid stayed capped at the
 *   trial allowance (F3, A4).
 * - `GET /api/admin/audit` is new, and it is the read side of a table that has
 *   been written by the console, by activation and by every owner-side action
 *   for some time, and read by nothing (A2).
 * - `GET /api/admin/plans` is new too, and exists so the picker is built from
 *   the catalogue rather than from four tier names retyped here. A tier added
 *   in Python appears in the console by existing.
 *
 * Kept out of `lib/api.ts` because that file is shared with four other streams;
 * only the `AdminTenant` shape needed extending there.
 */

import { apiFetch, type CallOpts } from "@/lib/api";

// ---------------------------------------------------------------------------
// The plan catalogue
// ---------------------------------------------------------------------------

/** No mapping: the wire shape is already camelCase-clean. */
export interface AdminPlan {
  key: string;
  name: string;
  entitlements: Record<string, number>;
}

export const adminPlans = {
  /** Ordered by quota, the way an upgrade page renders. */
  list: (opts: CallOpts = {}) => apiFetch<AdminPlan[]>("/api/admin/plans", opts),
};

// ---------------------------------------------------------------------------
// The manual billing adapter
// ---------------------------------------------------------------------------

export type SubscriptionStatus = "active" | "trialing" | "past_due" | "canceled";

interface AdminSubscriptionDto {
  plan_key: string;
  plan_name: string;
  status: string;
  provider: string;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
}

export interface SetSubscriptionPayload {
  planKey: string;
  status?: SubscriptionStatus;
  currentPeriodEnd?: string | null;
  cancelAtPeriodEnd?: boolean;
}

export const adminSubscription = {
  /**
   * Record what a tenant is on. Entitlements are rewritten from the catalogue
   * as a side effect, which is the entire point: this is the same path a
   * merchant-of-record webhook takes, so the manual route and the automatic
   * one cannot disagree about what a plan grants.
   */
  set: (tenantId: string, payload: SetSubscriptionPayload, opts: CallOpts = {}) =>
    apiFetch<AdminSubscriptionDto>(`/api/admin/tenants/${tenantId}/subscription`, {
      method: "PUT",
      body: {
        plan_key: payload.planKey,
        status: payload.status ?? "active",
        ...(payload.currentPeriodEnd !== undefined
          ? { current_period_end: payload.currentPeriodEnd }
          : {}),
        ...(payload.cancelAtPeriodEnd !== undefined
          ? { cancel_at_period_end: payload.cancelAtPeriodEnd }
          : {}),
      },
      ...opts,
    }).then((dto) => ({
      planKey: dto.plan_key,
      planName: dto.plan_name,
      status: dto.status,
      provider: dto.provider,
      currentPeriodEnd: dto.current_period_end,
      cancelAtPeriodEnd: dto.cancel_at_period_end,
    })),
};

// ---------------------------------------------------------------------------
// The audit trail
// ---------------------------------------------------------------------------

interface AuditEntryDto {
  id: string;
  tenant_id: string;
  tenant_name: string | null;
  action: string;
  target: string | null;
  created_at: string;
  actor_email: string | null;
  actor_role: string | null;
  impersonated_by: string | null;
  meta: Record<string, unknown>;
}

export interface AuditEntry {
  id: string;
  tenantId: string;
  tenantName: string | null;
  action: string;
  target: string | null;
  createdAt: string;
  actorEmail: string | null;
  actorRole: string | null;
  /**
   * The admin behind an impersonated session.
   *
   * An impersonated token carries the *owner's* identity, so without this a row
   * reads as the customer having done it. It is the reason impersonation is
   * audited at all.
   */
  impersonatedBy: string | null;
  meta: Record<string, unknown>;
}

export interface AuditPage {
  items: AuditEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditQuery {
  tenantId?: string;
  actor?: string;
  action?: string;
  limit?: number;
  offset?: number;
}

function mapAuditEntry(dto: AuditEntryDto): AuditEntry {
  return {
    id: dto.id,
    tenantId: dto.tenant_id,
    tenantName: dto.tenant_name,
    action: dto.action,
    target: dto.target,
    createdAt: dto.created_at,
    actorEmail: dto.actor_email,
    actorRole: dto.actor_role,
    impersonatedBy: dto.impersonated_by,
    meta: dto.meta ?? {},
  };
}

export const adminAudit = {
  /** Newest first. Actor and action are substring matches. */
  list: (query: AuditQuery = {}, opts: CallOpts = {}) => {
    const params = new URLSearchParams();
    if (query.tenantId) params.set("tenant_id", query.tenantId);
    if (query.actor) params.set("actor", query.actor);
    if (query.action) params.set("action", query.action);
    params.set("limit", String(query.limit ?? 50));
    params.set("offset", String(query.offset ?? 0));

    return apiFetch<{
      items: AuditEntryDto[];
      total: number;
      limit: number;
      offset: number;
    }>(`/api/admin/audit?${params.toString()}`, opts).then(
      (dto): AuditPage => ({
        items: dto.items.map(mapAuditEntry),
        total: dto.total,
        limit: dto.limit,
        offset: dto.offset,
      }),
    );
  },
};
