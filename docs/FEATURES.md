# Qonvo — Product Feature Overview

_A quick, plain-language map of what the product does, what each API endpoint is for,
which features live "under the hood" (not tied to any single endpoint), and where the
gaps and bugs are. Read this first for a fast overview._

Qonvo puts an **AI customer rep on a business's WhatsApp number**. It answers 24/7 from the
business's own knowledge, in the customer's language, by text and voice, and can take actions
(bookings, orders, leads, sheet writes). It is **multi-tenant** — many businesses on one system,
each fully isolated. Owners never run code; they use a web dashboard.

---

## 1. The story so far (three chapters)

### Chapter 1 — What was built originally (the baseline)
Before this cycle, the product already had:
- **The WhatsApp brain.** Incoming message → understand it → find the answer in the business's
  knowledge (RAG) → reply in the customer's language. Grounded: if the answer isn't in the
  knowledge, it says so and hands off instead of making things up.
- **Voice.** Understands voice notes (speech-to-text) and can reply with a voice note (text-to-speech).
- **Human takeover.** If the owner replies from their own phone, the bot goes quiet and lets the
  human handle it; it auto-resumes later.
- **Knowledge manager.** Owner uploads files / pastes text; it's chunked and embedded for search.
- **Skills (actions).** Book appointments, take orders, capture leads, write to Google Sheets,
  check calendar availability, share payment details, hand off to a human.
- **Google integrations.** Per-tenant Google login (OAuth) for Calendar + Sheets.
- **Dashboard + Admin console.** Inbox, knowledge, settings, and an internal ops console.
- **Sign in with Google (SSO)** for dashboard login.

### Chapter 2 — This cycle: testing after SSO, and the gaps we found
After SSO landed, we tested the product against how real competitors (Wati, AiSensy, Chatbase)
behave. We found serious gaps — mostly **money leaks, abuse holes, and missing admin/owner controls**:

| Gap we found | Why it mattered |
|---|---|
| Trial abuse wide open | A free trial could burn unlimited AI credits for 14 days — no message cap. |
| Cost recorded as $0 | We were running Gemini 2.x but the price table only had old models → every reply logged $0.00. Invisible spend. |
| No rate limiting | One customer could flood the number and run up the bill; nothing capped sustained inbound. |
| Voice unmetered | Voice minutes were never recorded, and a huge audio file could force a giant transcription bill. |
| Images broken | Photos were passed to the AI as an internal URL it couldn't reach → the AI was silently blind to every image. |
| Dead "summary" cost | A conversation summary was generated every few turns (an AI call) but never actually used → pure waste. |
| Unbounded RAG context | Every reply stuffed in ~3k tokens of knowledge, duplicates included → inflated cost on every turn. |
| Admin couldn't manage tenants | No way to suspend, delete, change plan, or recover a locked-out owner. |
| No mailbox | No transactional email (welcome, password reset, verification). |
| No self-serve signup | New businesses couldn't sign themselves up on a trial. |
| Misleading errors | UI said "backend not connected" instead of the real error. |
| No billing visibility | Owners couldn't see their trial status / days left. |

### Chapter 3 — What we added to make it robust
Everything below is now built, tested, and live on `main`:
- **Cost & abuse controls** (see the "Under-the-hood features" table): trial hard quota, real
  cost recording, per-conversation rate limit, voice metering + audio-size cap, image fix,
  summary now used, RAG budgeting.
- **Self-serve signup + free trial** with a hard message quota.
- **Transactional email** (welcome, password reset) — config-driven (log / Resend / SMTP).
- **Account security**: change password, forgot/reset password (single-use links).
- **Admin tenant lifecycle**: suspend / reactivate, change plan, set trial end, delete (purges
  all tenant data), plus an overview dashboard.
- **Admin fleet control**: start / stop / restart / logout any tenant's WhatsApp session.
- **Admin support tools**: reset a locked-out owner's password; impersonate a tenant (API only).
- **Owner billing visibility**: trial status + days left.
- **Website/URL knowledge sources** (not just file uploads).
- **Clear error messages** end-to-end.

---

## 2. API reference (endpoint → what it does)

> Auth: owner endpoints need a logged-in tenant user; `/api/admin/*` needs the `qonvo_admin` flag;
> `/webhooks/*` is machine-to-machine (HMAC-signed).

### Public / infra
| Method | Path | What it does |
|---|---|---|
| GET | `/healthz` | Liveness check. |
| GET | `/metrics` | Prometheus metrics (requests + pipeline). |
| POST | `/webhooks/waha` | **Main ingress** — every inbound WhatsApp message arrives here. |

### Auth & account
| Method | Path | What it does |
|---|---|---|
| POST | `/api/auth/login` | Email + password login → JWT. |
| POST | `/api/auth/signup` | **Self-serve signup** → new tenant on a free trial + welcome email. |
| POST | `/api/auth/google` | **Sign in with Google (SSO)** → JWT. |
| POST | `/api/auth/change-password` | Change password (must know the current one). |
| POST | `/api/auth/forgot-password` | Emails a single-use reset link. |
| POST | `/api/auth/reset-password` | Consume the reset link, set new password. |
| GET | `/api/me` | Who am I (identity, tenant, role). |

### Conversations (inbox)
| Method | Path | What it does |
|---|---|---|
| GET | `/api/conversations` | List conversations. |
| GET | `/api/conversations/{id}/messages` | Message history for one chat. |
| POST | `/api/conversations/{id}/takeover` | Human takes over → bot goes quiet. |
| POST | `/api/conversations/{id}/release` | Hand back to the bot. |
| POST | `/api/conversations/{id}/reply` | Human sends a manual reply. |

### Knowledge
| Method | Path | What it does |
|---|---|---|
| GET | `/api/knowledge/sources` | List knowledge sources. |
| POST | `/api/knowledge/sources` | Add a source (text **or URL/website**). |
| GET/PUT/DELETE | `/api/knowledge/sources/{id}` | Read / edit / delete a source. |
| POST | `/api/knowledge/sources/{id}/upload` | Upload a file to a source. |
| GET | `/api/knowledge/gaps` | Questions customers asked that the knowledge couldn't answer. |

### Settings, billing, notifications
| Method | Path | What it does |
|---|---|---|
| GET/PUT | `/api/config` | Read / update tenant settings (persona, tone, hours, voice mode, payment details…). |
| GET | `/api/billing` | Owner's plan, trial status, days left, expired flag. |
| GET | `/api/notifications` | Owner alerts (e.g. handoff needed). |
| POST | `/api/notifications/{id}/read` | Mark an alert read. |
| GET | `/api/onboarding` | First-run checklist (business info, WhatsApp, knowledge, integrations). |

### Team & account (owner)
| Method | Path | What it does |
|---|---|---|
| GET | `/api/team` | Members + pending invitations. |
| POST | `/api/team/invitations` | Invite a teammate (email + role); sends the invite email. |
| DELETE | `/api/team/invitations/{id}` | Revoke a pending invite. |
| DELETE | `/api/team/members/{user_id}` | Remove a member (never the last owner). |
| GET | `/api/team/invitations/accept/{token}` | **Public** — preview an invite. |
| POST | `/api/team/invitations/accept` | **Public** — accept: create user + membership. |
| GET | `/api/account/export` | **GDPR** — full tenant data as one JSON document. |

### WhatsApp sessions (owner side)
| Method | Path | What it does |
|---|---|---|
| GET/POST | `/api/sessions` | List / create a WhatsApp session. |
| GET | `/api/sessions/{name}/status` | Live connection status. |
| GET | `/api/sessions/{name}/qr` | QR image to link the phone. |

### Integrations (Google)
| Method | Path | What it does |
|---|---|---|
| GET | `/api/integrations` | List connected integrations. |
| POST | `/api/integrations/{provider}/oauth/start` | Begin Google connect. |
| GET | `/api/integrations/oauth/callback` | Google redirects back here; stores the grant. |
| POST | `/api/integrations/google_calendar/provision` | Create the "Qonvo Bookings" calendar. |
| GET | `/api/integrations/google_sheets/picker-token` | Token for the browser sheet-picker. |
| POST | `/api/integrations/google_sheets/select` | Save the chosen sheet. |
| POST | `/api/integrations/google_sheets/create` | Create a new sheet. |
| PUT/DELETE | `/api/integrations/{provider}` | Update config / disconnect. |
| POST | `/api/integrations/{provider}/test` | Test the connection. |

### Analytics
| Method | Path | What it does |
|---|---|---|
| GET | `/api/analytics/summary` | Conversation / message / cost summary. |

### Admin console (`qonvo_admin` only)
| Method | Path | What it does |
|---|---|---|
| GET | `/api/admin/overview` | Fleet-wide stats. |
| GET/POST | `/api/admin/tenants` | List / create tenants. |
| GET | `/api/admin/tenants/{id}` | Tenant detail + config. |
| PATCH | `/api/admin/tenants/{id}` | **Lifecycle** — name, status (suspend/reactivate), plan, trial end. |
| DELETE | `/api/admin/tenants/{id}` | **Delete tenant** — purges all its data + WAHA sessions. |
| PUT | `/api/admin/tenants/{id}/config` | Edit a tenant's settings. |
| GET | `/api/admin/fleet` | All WhatsApp sessions + live status. |
| POST | `/api/admin/fleet/{session}/{action}` | **Session control** — start / stop / restart / logout. |
| POST | `/api/admin/tenants/{id}/reset-password` | **Recover** a locked-out owner (one-time password). |
| POST | `/api/admin/tenants/{id}/impersonate` | **"Log in as" tenant** (mints owner token; API only — no UI yet). |
| GET | `/api/admin/usage` | Per-tenant usage for invoicing. |

### AI Skills (not HTTP endpoints — the bot calls these mid-conversation)
| Skill | What it does | Needs |
|---|---|---|
| `book_appointment` | Books a calendar event. | Google Calendar |
| `check_availability` | Checks free/busy before booking. | Google Calendar |
| `append_to_sheet` | Writes a row to a sheet. | Google Sheets |
| `lookup_sheet` | Reads/looks up a sheet. | Google Sheets |
| `take_order` | Records an order (→ `orders` table). | — |
| `share_payment_details` | Shares payment info verbatim. | `payment_details` set |
| `capture_lead` | Saves a lead. | — |
| `human_handoff` | Pauses bot + alerts the owner. | — |

---

## 3. Under-the-hood features (NOT tied to any single endpoint)

These are behaviors that run inside the pipeline / worker / webhook. They have **no API of their
own** — they just happen. This is the list to know about:

| Feature | Where it runs | What it does |
|---|---|---|
| **Trial hard quota** | pipeline gate | Trial tenant capped at 300 messages/month; over → polite "team will reach out". |
| **Per-conversation rate limit** | webhook | Drops >20 msgs/60s from one chat (Redis). Stops flood/abuse. |
| **Real cost recording** | pipeline | Logs true $ per reply from a per-model price table; warns (not $0) on a price miss. |
| **Voice metering** | pipeline | Records voice seconds (in + out) for billing/visibility. |
| **Inbound audio cap** | pipeline | Skips voice notes > 8 MB before transcription (no giant STT bill). |
| **Image → vision** | pipeline | Downloads photos and inlines them so the AI can actually see them. |
| **Image size cap** | pipeline | Skips images > 5 MB. |
| **Rolling summary** | pipeline | Compresses old turns and feeds them back so long chats keep memory. |
| **RAG context budget** | pipeline | Caps knowledge context at ~2k tokens; drops duplicate chunks. |
| **Message dedupe** | webhook | Ignores duplicate WhatsApp deliveries (Redis + DB unique). |
| **Debounce / burst coalescing** | webhook + worker | Waits ~5s and merges rapid-fire messages into one turn. |
| **Own-send echo skip** | webhook | Ignores the bot's own outgoing messages (or it would silence itself). |
| **Implicit human takeover** | webhook | Owner replies from phone → bot pauses; auto-resumes after a TTL. |
| **Business-hours auto-reply** | pipeline gate | Off-hours → one "we're closed" reply. |
| **Suspended/expired gate** | pipeline gate | Suspended tenant or expired trial → bot goes silent. |
| **Send pacing** | send gateway | Human-like delays + daily send cap (ban-safety). |
| **Booking reminders** | scheduler | Confirmation + 24h reminder, capped 2/booking, opt-out on "stop". |
| **Knowledge-gap logging** | pipeline | Records questions the knowledge couldn't answer (see `/api/knowledge/gaps`). |
| **Row-Level Security (RLS)** | everywhere | DB-enforced tenant isolation; no tenant can ever see another's data. |
| **Transactional email** | services | Welcome + password-reset emails (log / Resend / SMTP). |
| **Config-driven AI providers** | providers | LLM/embeddings/STT/TTS swappable per tenant (OpenAI / Gemini / Groq / custom). |

---

## 4. Known gaps & bugs (honest list)

### Recently completed (this cycle — now built ✅)
- **Team / staff seats** ✅ — `team_invitations` table (migration 0006), `/api/team`
  invite/list/revoke/remove + public `/accept-invite`, owner-gated, in the dashboard.
- **Data export (GDPR)** ✅ — `GET /api/account/export` + a dashboard download button.
  (Self-serve *deletion* stays admin-mediated on purpose — see below.)
- **Owner notification preferences** ✅ — `notify_on_handoff` toggle in Settings.
- **First-run onboarding checklist** ✅ — derived `/api/onboarding` + a Settings card.

### Still missing (need an external decision, not just code)
- **Automated billing / payments** — plan/trial are tracked, but there's no payment collection;
  upgrading to "paid" is a manual admin action. _Blocked on a payment-provider choice + keys._
- **CRM sync** — wanted, not built (Sheets is the current stand-in). _Blocked on a CRM choice._
- **Self-serve account deletion** — intentionally admin-only (`DELETE /api/admin/tenants/{id}`)
  so an irreversible purge always goes through an operator, not one owner click.
- **Impersonation UI** — the endpoint exists, but "log in as tenant" has no dashboard button yet
  (needs an Auth.js session-swap).

### Known bugs / rough edges
- **Token undercount (~25–35%).** We count tokens from the provider's usage field; Gemini
  sometimes omits it, so cost can be slightly under-reported. (Never over-reported.)
- **Voice minutes are an estimate.** Metered from audio byte-size (≈2 KB/s), not exact duration —
  fine for visibility, not for to-the-second invoicing.
- **No media beyond text / voice / image.** Video, documents, stickers, and location messages
  aren't handled — they're effectively ignored.
- **Ingestion format gaps.** URL + common file types work, but no XLSX / PPTX / scanned-PDF (OCR)
  parsing, and there's **no per-tenant knowledge storage quota**.
- **No model routing.** Every turn uses the same model; no "cheap model for simple messages".
- **Old migration no-op** (`0004_billing.py`) — a stray `UPDATE` in it silently affects 0 rows
  because of table ownership. Harmless now, but noted.
- **Prompt caching not used.** Provider prompt-caching (cheaper repeated system prompts) is off.

### Coordination note (current)
A parallel "Qonvo Personal" (individual users, not just businesses) effort lives on branch
`qonvo-personal-milestone-a` with its own DB migration (`0005`). To avoid a migration-number
clash, **no new migrations have been added to `main`** — so the migration-dependent backlog items
above (team seats, self-serve data export) are deferred until that branch merges.

---

_Last updated: 2026-08-16. Source of truth for architecture is [`DESIGN.md`](../DESIGN.md); this
file is the fast feature/endpoint overview._
