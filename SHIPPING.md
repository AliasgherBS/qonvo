# Qonvo — Shipping Model, Dashboards & Road to Market-Ready

How the product is delivered, what the two dashboards are, and the honest gap
list between "works end-to-end in dev" (where we are) and "sell it to the masses"
(where we're going). Companion to [`USAGE.md`](USAGE.md) (how to operate it) and
[`DESIGN.md`](DESIGN.md) (architecture).

---

## 1. The two-platform model (this was the intent from day one)

Qonvo ships as **two dashboards on one codebase**, split by role (see
[`USAGE.md`](USAGE.md) §0):

### A. Admin platform — *you / Qonvo staff* (`qonvo_admin`)
The control tower over every business on the platform. Routes under `/admin/*`:

| View | Shows | Status |
|---|---|---|
| **Tenants** (`/admin/tenants`) | Every business, its owner, status, created date. Create a business + issue the owner's one-time password. | ✅ built |
| **Fleet Health** (`/admin/fleet`) | Every WhatsApp session across all tenants — who's connected, live status (WORKING / needs-scan / failed). | ✅ built |
| **Usage** (`/admin/usage`) | Per-tenant messages, tokens, AI cost — the basis for invoicing. | ✅ built |

This already answers "how many businesses, who connected a session, who's using
it, and how much." **Gap:** there's no single **overview tile** (totals: # tenants,
# live sessions, # knowledge sources ingested, messages this month) and no
per-tenant **knowledge-ingested count**. That's a small, high-value add — see §4.

### B. User platform — *the business owner* (`owner`)
The dashboard a customer logs into to run their AI rep. This is what exists today:

| View | Purpose |
|---|---|
| **WhatsApp** (`/onboarding/connect`) | Link the business number (QR scan). |
| **Inbox** (`/inbox`) | Live conversations, take over / hand back to the bot. |
| **Knowledge** (`/knowledge`) | Teach the bot (paste / upload); see answer gaps. |
| **Integrations** (`/integrations`) | Connect Google Calendar / Sheets. |
| **Settings** (`/settings`) | Persona, hours, language, payments, voice, LLM. |
| **Analytics** (`/analytics`) | Messages, leads, bookings, orders, cost, top gaps. |

Both roles are fully click-through today (no more "reachable only by URL").

---

## 2. How we ship a customer (the onboarding flow)

Current (admin-provisioned) path — works today:

1. **Admin** creates the tenant in `/admin/tenants` → hands the owner a one-time password.
2. **Owner** signs in → **WhatsApp** → scans the QR from the business phone.
3. **Owner** adds knowledge, sets persona/hours, optionally connects Google.
4. Customers message the number → the bot answers 24/7, grounded in that knowledge,
   escalating or acting via skills.

For **self-serve at scale**, step 1 becomes a public signup + billing flow (§4).

---

## 3. Production reality of the WhatsApp layer (read this carefully)

We drive WhatsApp through **WAHA** using the **NOWEB engine** (websocket, Baileys-based).

**Is it production-grade?** Yes — NOWEB is the engine WAHA recommends for
production: no headless browser, lower memory, more stable than WEBJS (which we
hit two blocking bugs on). It's widely run in production.

**But it is the *unofficial* WhatsApp protocol**, and that has real consequences
you must plan for:

- **Ban risk.** Unofficial automation can get a number banned — highest for
  bulk/broadcast, lowest for reactive 1:1 replies (what Qonvo does). We keep the
  only bot-initiated outbound (booking reminders) capped and opt-out-able. Still,
  advise customers to use a number they can afford to lose, warm it up, and never
  bulk-message.
- **WhatsApp updates can break it.** Because it rides the reverse-engineered Web
  protocol, a WhatsApp-side change can break connect/messaging (we just lived
  this: 2026.6.2 → both engines broke; 2026.7.2 fixed it). **Mitigation:** keep
  WAHA updated (they track WhatsApp fast), and 2026.7.2+ exposes
  `WAHA_NOWEB_WA_VERSION_FORCE` to pin a working version in a pinch. Budget for
  occasional "bump WAHA" maintenance — this is inherent to unofficial WhatsApp.
- **The stable long-term answer is the official WhatsApp Cloud API** (Meta): no
  ban risk, no protocol breakage — but it costs per-conversation, needs business
  verification, and restricts free-form replies to a 24h window (templates
  outside it). The codebase is built to add it as a second provider later; offer
  it as the "trust/scale" tier.

**Scaling to many concurrent tenants/sessions:**
- Each NOWEB session = one websocket + a store; memory grows per session. One VPS
  handles a modest fleet (dozens); for hundreds/thousands, **shard WAHA across
  multiple instances** (the per-session webhook + tenant resolution already
  supports this) and/or move to **WAHA Plus**. Confirm the Core session ceiling
  and per-session footprint before you promise scale.
- Everything else (FastAPI, workers, Postgres+RLS, Redis) scales horizontally the
  usual way; the app is multi-tenant from day one.

**Bottom line:** NOWEB on a pinned, kept-current WAHA is the right MVP-through-
early-growth choice. For "the masses," pair it with (a) a WAHA scaling/sharding
plan and (b) an official Cloud API option for customers who need zero ban risk.

---

## 4. Last mile — what's between here and market-ready

**Done / working:** multi-tenant core, RLS isolation, RAG-grounded replies (text
+ voice-in), skills (leads/orders/handoff/booking/sheets/payments), inbox +
takeover, analytics, admin console, live WhatsApp round-trip on NOWEB, both
critical engine bugs fixed.

**Still needed to sell to the masses:**

| Area | Gap | Priority |
|---|---|---|
| **Billing** | ✅ Built and provider-agnostic (plans, subscriptions, entitlements, grace/cancel states, webhook route), shipped on the manual adapter. Needs a merchant-of-record account to take money automatically. | 🟠 should |
| **Self-serve signup** | ✅ Built (`POST /api/auth/signup`, 14-day trial). | ✅ done |
| **WAHA scale** | Sharding/Plus plan + session-count monitoring for many tenants. | 🔴 must |
| **Reconnect UX** | On session drop, notify owner + guided re-scan (health monitor exists; wire the owner-facing nudge). | 🟠 should |
| **Official Cloud API** | Second provider for zero-ban-risk / high-trust customers. | 🟠 should |
| **Admin overview** | ✅ Built (overview tiles + `/admin/health`). | ✅ done |
| **Voice-out** | Add an OpenAI TTS key to enable voice replies (STT already works). | 🟡 nice |
| **Ops hardening** | Alerting ✅ (Prometheus/Grafana/Alertmanager), rate-limit/abuse ✅, staging env ✅ (`./qonvo-staging.sh`). **Backups are still unscheduled — the script exists, cron does not.** No CI. | 🔴 must |
| **Legal/compliance** | WhatsApp ToS posture, privacy policy, data-retention/DPA, per-tenant data export/delete. | 🟠 should |
| **CRM sync** | Push leads/orders to external CRMs. | 🟡 want |

**Suggested sequence to launch:** (1) self-serve signup + billing → (2) WAHA
scaling plan + reconnect UX → (3) admin overview + ops hardening → (4) official
Cloud API tier. Phases 0–3 (the product itself) are effectively done; the last
mile is mostly **commercialization + scale plumbing**, not core features.
