# Qonvo billing: design

**Date:** 2026-09-04
**Status:** approved, implementing
**Scope:** `backend/` billing subsystem + the owner-facing billing surface. No
change to the agent pipeline beyond the service gate it already has.

## 1. Why

Plans and trials are tracked, but there is no way to take money. `tenants.plan`
is a two-value string (`trial` / `paid`), entitlements are hand-written JSON on
`tenant_config`, and moving a business to paid is an admin editing a field. There
is no record of what anyone agreed to pay, when a period ends, or why service
stopped.

## 2. The constraint that shapes it

Qonvo will sell through a **merchant of record** (Paddle or Polar). No account
exists yet, so nothing can be integrated today. That is not a reason to wait: an
MoR owns the subscription, the pricing, the tax and the dunning, and tells us
about all of it through **webhooks**. Our side is therefore a *reconciler*, not a
billing engine, and the interface a reconciler needs is the same interface an
admin marking an invoice paid satisfies.

So: build the domain now, ship it with an **admin adapter**, and add the MoR
adapter later as one file plus a webhook route.

**Money never lives here.** No card data, no price arithmetic, no proration, no
invoice generation. Prices stay in the MoR — deliberately not in this repo, which
also keeps the "no price figures in code" gate the frontend work established.

## 3. Shape

```
app/billing/
  plans.py          catalogue: plan key → entitlements (no prices)
  state.py          pure decision: is this tenant entitled to service?
  service.py        IO: apply a plan, record an event, reconcile a subscription
  providers/
    base.py         BillingProvider protocol + BillingEvent
    manual.py       admin-driven; the shipped default
    registry.py     resolve from settings
```

### 3.1 Plans live in code, not the database

A plan is a *contract about entitlements*, and entitlements belong in git where
they are reviewable and testable. Prices are the MoR's business. A DB table would
buy admin CRUD we do not need for four rarely-changing rows, at the cost of a
migration, an API and a UI.

Provider price ids map to plan keys through settings
(`QONVO_BILLING_PRICE_MAP`), so adding a Paddle price never needs a deploy of the
catalogue.

| key | monthly messages | seats |
|---|---|---|
| `trial` | 300 | 2 |
| `starter` | 1,000 | 2 |
| `growth` | 5,000 | 5 |
| `scale` | 20,000 | 15 |

`tenant_config.entitlements` stays the runtime source the pipeline reads, but it
becomes **derived**: `apply_plan()` writes it from the catalogue. One source of
truth, and a plan change can never leave a stale quota behind.

### 3.2 Two tables (migration 0008)

**`subscriptions`** — one per tenant: `plan_key`, `status`, `provider`,
`provider_subscription_id`, `provider_customer_id`, `current_period_end`,
`cancel_at_period_end`.

**`billing_events`** — every provider event, keyed by `provider_event_id`
(unique). This is the idempotency ledger: MoRs retry webhooks, and a replayed
`subscription.canceled` must not cancel a resubscribed tenant.

Both tenant-scoped under RLS, with the explicit `GRANT` the codebase requires for
migration-owner-created tables.

### 3.3 The gate is a pure function

`state.py::service_state(...) -> ServiceState` answers one question: may this
tenant's bot reply right now? It takes the tenant status, the legacy plan/trial
fields, the subscription, and `now`; it returns `active` or a blocked reason. No
database, no clock.

Rules, in order:

1. Tenant suspended → **blocked**(`suspended`).
2. Subscription `active` or `trialing` → **active**.
3. Subscription `past_due` → **active** during a grace window
   (`QONVO_BILLING_GRACE_DAYS`, default 7) measured from `current_period_end`,
   then **blocked**(`past_due`). A card that failed on Tuesday must not silence a
   business on Tuesday.
4. Subscription `canceled` → **active** until `current_period_end`, then
   **blocked**(`canceled`). They paid for the period.
5. No subscription row (every tenant today) → the existing behaviour: trial past
   `trial_ends_at` is **blocked**(`trial_expired`), anything else **active**.

Rule 5 is what makes this deployable without a backfill.

### 3.4 The provider interface

```python
class BillingProvider(Protocol):
    key: str
    def checkout(self, tenant_id, plan) -> Checkout: ...
    def parse_event(self, headers, raw) -> BillingEvent | None: ...
```

`Checkout` is either a redirect URL (MoR) or an instruction string (manual).
`parse_event` returns `None` when a signature fails, so the route answers 401
without the route knowing anything about any provider's signing scheme.

`BillingEvent` is normalised: `(provider, event_id, type, plan_key,
subscription_id, customer_id, status, current_period_end)`. Adapters translate;
`service.py` only ever sees this.

### 3.5 Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/billing` | extended: subscription, entitlements, usage this period |
| GET | `/api/billing/plans` | the catalogue, for an upgrade view |
| POST | `/api/billing/checkout` | `{plan}` → redirect URL, or manual instructions |
| POST | `/webhooks/billing/{provider}` | signature-verified, idempotent |
| PUT | `/api/admin/tenants/{id}/subscription` | the manual adapter's "mark paid" |

## 4. What is deliberately not here

- **Prices, proration, invoices, tax, dunning emails.** The MoR's job.
- **Usage-based overage billing.** `usage_counters` already records what an
  overage charge would need; adding the charge is a pricing decision nobody has
  made.
- **Voice or feature gating by plan.** Only quota and seats gate today. More
  gates are one entry in the catalogue plus one check, once a plan actually
  differs that way.
- **A self-serve downgrade flow.** Cancel goes through the MoR's own portal.

## 5. Testing

The catalogue, `service_state` and the event reconciler are pure and get direct
unit tests, including the grace window and the replayed-event case. The manual
adapter and the webhook route are tested with a fake provider, which is also the
proof that the route is genuinely provider-agnostic.
