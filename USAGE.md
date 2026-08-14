# Qonvo — Usage Guide

How to actually operate the platform end-to-end, in the order things happen: provisioning a
business, signing in, linking a WhatsApp number, teaching and configuring the AI rep, handling
live conversations, and monitoring usage. Grounded in the current code — file references point at
the source so you can verify any step.

For architecture and *why* things work this way, see [`DESIGN.md`](DESIGN.md). This document is
the *how-to-use*.

---

## 0. The two roles (read this first)

Qonvo has exactly two kinds of login, and they gate everything below:

| Role | Who | Sees | Backing |
|---|---|---|---|
| **Platform admin** (`qonvo_admin`) | You / Qonvo staff | *All* tenants, the fleet, cross-tenant usage. Creates businesses. | `users.is_qonvo_admin = true`, a cross-tenant flag — **not** a tenant membership. Runs on the `qonvo_system` role that bypasses row-level security. |
| **Tenant owner** (`owner`) | The business owner | *Only their own* business — their inbox, knowledge, settings, analytics. | A `TenantUser` membership with role `owner`. Every query is RLS-filtered to their `tenant_id`. |

There is **no self-signup**. A business account is always provisioned by a platform admin first (or
by the dev seed script). So the real sequence starts at the admin panel — but a tenant owner never
touches it. Below, **Part 1** is the admin step; **Parts 2–6** are the owner's day-to-day.

**Dev logins** (seeded by `scripts/seed_dev.py`, see [`CLAUDE.md`](CLAUDE.md)):
- Admin — `admin@qonvo.dev` / `dev-admin-123`
- Owner — `owner@dev.dev` / `dev-password-123`
- Dashboard — http://localhost:3002

---

## 1. Provision a business (platform admin)

The admin creates the tenant and its owner account; the owner receives a one-time password and
takes it from there.

1. **Sign in** at `/login` as the admin. Admin nav (`/admin/*`) only appears when your session role
   is `qonvo_admin`; owners are redirected away.
2. Go to **`/admin/tenants`** → click **"New tenant"**. Fill:
   - **Name** — the business name
   - **Slug** — URL-safe identifier (must be unique; duplicate → error)
   - **Owner email** and **Owner name**
3. Submit. The backend (`POST /api/admin/tenants`) creates the `Tenant`, a default config, and the
   owner `User`, then returns a **temporary password shown exactly once** in a dialog
   ("shown once, can't be retrieved"). Copy it and hand it to the business owner. The owner logs in
   with it and can change it later.
4. Every admin action writes an `audit_log` row.

**What else the admin can do** (nobody else can — these are cross-tenant):
- **`/admin/tenants/[id]`** — inspect any tenant and edit its config (same form as the owner's
  Settings, via `PUT /api/admin/tenants/{id}/config`).
- **`/admin/fleet`** — every WhatsApp session across every tenant, with DB status vs. **live** WAHA
  status side by side (a session showing `unreachable` means WAHA didn't answer).
- **`/admin/usage`** — per-tenant messages / tokens / cost, optionally filtered by month
  (`?month=YYYY-MM`). This is the manual-invoicing rollup.

> In dev, the seed script already created one tenant + owner, so you can skip straight to Part 2.

---

## 2. Sign in (tenant owner)

1. Open the dashboard (dev: http://localhost:3002) → you land on **`/login`**.
2. Enter **email** + **password** (the temp password from Part 1). Click **Sign in**.
3. On success you're taken to **`/inbox`**.

Mechanics: the dashboard (Auth.js, JWT session) calls the backend `POST /api/auth/login`, then
`GET /api/me`, and stores a 24-hour bearer token in the session. Every dashboard→backend call
carries that token; the backend derives your tenant and role entirely from its claims. All
dashboard routes except `/login` and `/api/auth/*` require a session.

---

## 3. Link the WhatsApp number (the "WhatsApp registry")

This is the QR-scan flow that puts the business's own WhatsApp number under Qonvo's control. It
uses WAHA (a WhatsApp gateway) under the hood — the same "Link a device" mechanism as WhatsApp Web.

1. Go to **`/onboarding/connect`** ("Connect your WhatsApp number").
2. Enter a **Session name** (free text, e.g. `main-support-line`) → click **Start connecting**.
   This calls `POST /api/sessions`, which creates a WAHA session, mints a per-session HMAC secret
   for webhook signing, and registers the inbound webhook.
3. The page polls session status every **5 s**. When status is **`SCAN_QR_CODE`**, a **QR code**
   renders (auto-refreshing every 15 s, because each QR expires in ~20 s).
4. On the **business phone**, open WhatsApp → **Settings → Linked devices → Link a device** → scan
   the QR.
5. When status flips to **`WORKING`**, you'll see a green **"Live and watching for messages"**
   badge. The number is now connected — inbound customer messages start flowing to the AI.
   If it shows **`FAILED`**, hit **Try again** to start a fresh session.

**Session states:** `STOPPED → STARTING → SCAN_QR_CODE → WORKING` (or `FAILED`).

Once `WORKING`, WAHA delivers every inbound message to `POST /webhooks/waha`, HMAC-signed with that
session's secret. The webhook resolves which tenant owns the session, verifies the signature, and
hands the message to the reply pipeline (Part 5).

> Reactive 1:1 replies only. Group, newsletter, and broadcast chats are ignored by design. The only
> bot-*initiated* messages are capped booking reminders (Part 6).

---

## 4. Set up the AI rep

Do these in any order; realistically **Knowledge + Settings** are the minimum to go live, and
**Integrations** unlock actions (booking, sheets).

### 4a. Teach it — Knowledge (`/knowledge`)

The bot answers **only** from what you give it here (strict grounding; it won't invent facts). Two
ways to add knowledge:

- **Add entry** (top-right) → paste a **Title** + **Content** by hand. Good for policies, FAQs,
  hours, pricing notes.
- **Upload** a file — drag-and-drop or browse. Accepts **PDF, DOCX, CSV**. The text is extracted,
  chunked (~500 tokens, 50 overlap), embedded, and stored for retrieval.

Each source shows a status badge: **Processing** (`pending_ingest`) → **Ready** or **Error**. A
source isn't searchable until it's **Ready** (ingestion runs asynchronously in the worker). Manual
entries are editable in place; uploaded files are read-only (re-upload to change them).

The **Gaps** tab lists the top questions customers asked that the bot *couldn't* answer (RAG found
nothing) — your backlog of knowledge to add.

> Note: a `website`/URL source type exists in the backend but has no UI yet — use paste or file
> upload for now. Uploaded files are stored on a local volume (`/data/knowledge`), not object
> storage.

### 4b. Configure it — Settings (`/settings`)

Every field and what it does:

| Field | Effect |
|---|---|
| **Business name** | "You are the AI customer representative for {name}" in the system prompt |
| **Persona** | Friendly / Professional / Playful / Formal / Direct — sets voice |
| **Tone** | Multi-select chips (Warm, Concise, Empathetic…) added to the prompt |
| **Primary language** | Default reply language (en/ur/ar/hi) when the customer's is unclear |
| **Custom instructions** | Free text appended verbatim to the prompt |
| **Business hours** | Per-day open/close + timezone + "Enforce" switch. When on and closed, the bot sends your closed-message once per conversation instead of answering |
| **Owner alert number (WhatsApp)** | Where handoff alerts are sent |
| **Payment / account details** | Shared verbatim by the payment skill. **Blank = payment skill disabled** |
| **Voice replies** | `match` (mirror the customer), `always`, or `never`. Requires an STT/TTS key to actually speak (see note) |
| **AI provider / Model** | Which LLM powers replies (OpenAI / OpenRouter / Groq / Gemini) + model id |

Click **Save changes** to persist (`PUT /api/config`).

> Voice needs a Groq/OpenAI STT+TTS key even if your LLM is Gemini (Gemini's OpenAI-compat surface
> has no audio endpoints). Without one, voice silently falls back to text.

### 4c. Connect actions — Integrations (`/integrations`)

Two providers, both Google via a **service account** (no OAuth):

- **Google Calendar** — enables the `book_appointment` / `check_availability` skills.
- **Google Sheets** — enables `append_to_sheet` / `lookup_sheet`.

For each: optionally paste a **service-account key (JSON)** (stored encrypted; blank = use the
platform's shared service account), then the **target ID** (Calendar ID or Spreadsheet ID) and the
second field (Timezone / Tab range). The card shows the service-account **email** — **share your
calendar/sheet with that email (edit access)**, then click **Save** and **Test connection**. Test
does a live read to confirm both the key works *and* the resource was actually shared.

**How gating works:** a skill stays hidden from the AI until its requirement is met. Connecting
Calendar makes the booking skills available; connecting Sheets makes the sheet skills available;
filling **Payment details** in Settings enables the payment skill. No integration = the bot simply
never offers that action. Status badge per card: **Connected** / **Needs setup** / **Not
connected**.

---

## 5. How a conversation is handled (the reply pipeline)

Once the number is `WORKING` and knowledge is `Ready`, this runs automatically for every inbound
1:1 message:

1. **Ingress & security** — webhook verifies the HMAC signature, resolves the tenant, ignores
   group/broadcast chats and the bot's own echoes, and **dedupes** repeats (24 h).
2. **Debounce (5 s)** — rapid-fire fragments ("hi" … "are you open?" … "today?") are buffered into
   one turn; the window slides on each new fragment so the bot replies once, coherently.
3. **Voice-in** — voice notes are transcribed to text (if an STT key is set) before processing.
4. **Gates** — the bot stays silent / auto-replies if: a human has taken over, the monthly message
   quota is hit, it's outside business hours, or the customer opted out of reminders.
5. **RAG** — retrieves the most relevant knowledge chunks (top 6). If none match, it logs a
   **knowledge gap** (surfaced in Knowledge → Gaps and Analytics).
6. **Reply + tools** — the LLM answers grounded in that context, and may call **skills** (below) in
   a bounded loop. Writes are idempotent (a retry never double-books).
7. **Voice-out** — per your Voice setting, the reply may be synthesized to a voice note.
8. **Persist & send** — the outbound message is logged, usage/cost counted, and sent via the paced
   send gateway (respecting the daily cap).

**Skills the AI can invoke:**

| Skill | Does | Needs |
|---|---|---|
| `capture_lead` | Save a prospect's contact + interest | — |
| `human_handoff` | Escalate to a human → sets conversation to **Needs human**, alerts the owner | — |
| `take_order` | Record an order (items, quantities, prices) → `orders` table | — |
| `share_payment_details` | Send payment/account details verbatim | Payment details set |
| `book_appointment` | Book on the calendar | Google Calendar |
| `check_availability` | Check the calendar before offering a time | Google Calendar |
| `append_to_sheet` | Append a lead/order/request row | Google Sheets |
| `lookup_sheet` | Look up stock/price/order status | Google Sheets |

---

## 6. Handle live chats — Inbox & takeover (`/inbox`)

The owner's operational screen. Two panes (conversation list + transcript), both auto-refreshing
every 5 s.

- **Filter tabs:** **All**, **Needs human**, **Paused**.
- Each conversation shows the customer chat, a **state badge**, a last-message preview, and an
  **unread dot**. Opening a thread clears its unread count.
- **Message labels:** **Bot** (AI), **You** (a human reply), **Customer**.

**Conversation states:**

| State | Meaning |
|---|---|
| **Bot active** | AI is handling it |
| **You're replying** (`paused_by_owner`) | A human took over; bot is paused |
| **Needs human** | The AI escalated (`human_handoff`) — needs your attention |
| (paused by agent) | Also shown as "Needs human" |

**Taking over:**
- Click **Take over** to pause the bot and reply yourself. The composer only unlocks in this state
  ("You're replying"). Your replies go out through the same paced gateway and are logged as
  **human**.
- Click **Resume bot** to hand control back.
- **Implicit takeover:** if you just reply to the customer *from your own phone*, Qonvo detects it
  and pauses the bot automatically — no need to touch the dashboard.
- **Auto-resume:** a pause self-heals back to *Bot active* after **6 hours** if you don't act, so a
  forgotten takeover doesn't silence the bot forever.

---

## 7. Usage, analytics & logging

### Owner analytics (`/analytics`)

`GET /api/analytics/summary?days=30` (default 30, your tenant only). The page shows:
- **Stat cards:** Messages, Conversations, Leads, Bookings, Orders, Needs-human, Open handoffs,
  AI cost.
- **Daily volume** bar chart (messages in/out per day).
- **Top questions the bot couldn't answer** (the knowledge gaps).

### What gets logged (per conversation)

Everything is stored per-tenant and RLS-isolated. Key tables:

| Table | Holds |
|---|---|
| `conversations` | One per customer chat: `state`, `summary`, `unread_count`, `paused_until`, activity timestamps. A partial unique index keeps one *active* conversation per chat; closed ones are retained. |
| `messages` | Every message: `direction` (inbound/outbound), `author` (customer/bot/human), `type` (text/voice/image/…), `body`, `transcript` (voice→text), `lang`, `tokens`, `cost`, `wa_message_id`, timestamps. |
| `leads` | Captured prospects (name/phone/email/notes/score). |
| `bookings` | Appointments: `scheduled_at`, `status`, `external_event_id`, reminder timestamps. |
| `orders` | `take_order` output: `items` (JSON), `total`, `currency`, `status`. |
| `handoffs` | Escalations: `status` (open/resolved), `reason`. |
| `reminder_suppressions` | Per-phone reminder opt-out list. |
| `usage_counters` | Daily rollup per tenant: messages in/out, voice seconds, tokens, cost — the billing source. |
| `analytics_events` | e.g. `knowledge_gap` events feeding the Gaps view. |
| `notifications` | Dashboard alerts (escalation, session-failed). |
| `failed_jobs` | Dead-letter queue for jobs that exhausted retries. |

Message history endpoints (owner, tenant-scoped): `GET /api/conversations`,
`GET /api/conversations/{id}/messages`, plus `takeover` / `release` / `reply`.

### Alerts & notifications

- **Dashboard notifications** (`GET /api/notifications`): an **escalation** row on every
  `human_handoff`; a **session_failed** row when a WhatsApp session drops to `FAILED`.
- **Email owner-alert:** fired **only** by `human_handoff` ("A customer needs a human"). Transport
  is config-driven — `log` (dev default), `resend`, or `smtp`. Best-effort; never blocks a reply.
- **WhatsApp alert** to the owner's alert number on handoff (if set).

### Booking reminders (bot-initiated, capped)

The scheduler runs every **15 minutes**. For bookings made through a chat, it sends at most **two**
messages per booking — a **confirmation** and a **24-hour-before reminder** — each tracked by its
own timestamp so re-runs never double-send. It respects business hours and the opt-out list (a
customer replying "stop" / "unsubscribe" / Urdu "band karo" is suppressed). This is the *only*
outbound the bot initiates on its own.

### Platform metrics (`/metrics`, admin/ops)

Prometheus text endpoint exposing HTTP request counts and latencies by route/method/status
(`qonvo_http_requests_total`, `qonvo_http_request_duration_seconds_*`). It's request-level
observability, not business metrics — those live in `/analytics` and `/admin/usage`.

---

## Quick reference — routes

**Dashboard (owner):** `/login` · `/inbox` · `/onboarding/connect` · `/knowledge` · `/settings` ·
`/integrations` · `/analytics`
**Dashboard (admin):** `/admin/tenants` · `/admin/tenants/[id]` · `/admin/fleet` · `/admin/usage`

**Backend API (prefixes):** `/api/auth/login`, `/api/me` · `/api/sessions/*` · `/webhooks/waha` ·
`/api/knowledge/*` · `/api/config` · `/api/integrations/*` · `/api/conversations/*` ·
`/api/analytics/summary` · `/api/notifications/*` · `/api/admin/*` · `/metrics`

**End-to-end happy path:** admin creates tenant → owner signs in → links WhatsApp (QR) → adds
knowledge + saves settings → (optionally connects Google) → customers message the number → AI
replies grounded in the knowledge, escalating or acting via skills → owner watches the inbox, takes
over when needed, and tracks volume/cost in analytics.
