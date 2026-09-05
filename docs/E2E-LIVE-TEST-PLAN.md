# Qonvo end-to-end live test plan

*Where we stand, what a machine can check, and what only you can. Run part 1
before every release; run part 2 before anything a customer will touch.*

Companion to `[TESTING.md](TESTING.md)` (unit and integration suites) and
`[USAGE.md](../USAGE.md)` (how to operate each screen).

---

## How this is split


| Part                     | Who runs it               | Covers                                                                                                                               | Time    |
| ------------------------ | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ------- |
| **1. Automated**         | `./scripts/e2e-smoke.sh`  | Auth, authorisation, every read endpoint, billing lifecycle, knowledge ingestion, the inbound pipeline via signed synthetic webhooks | ~2 min  |
| **2. Manual**            | You, with a phone         | The real WhatsApp round trip, voice, images, takeover, skills                                                                        | ~30 min |
| **3. External accounts** | You, once per environment | Google OAuth, email delivery, payment gateway                                                                                        | ~20 min |


Everything in part 1 is checked automatically because it needs no human. What
remains in parts 2 and 3 needs a physical phone, a Google consent screen, or an
account that does not exist yet. That boundary is the honest answer to "how much
can we test ourselves".

---



## Part 1 — automated

```bash
./qonvo-staging.sh up && ./qonvo-staging.sh migrate && ./qonvo-staging.sh seed
./scripts/e2e-smoke.sh                      # staging, the safe default
```

**Run it against staging.** It creates and deletes real rows: tenants, knowledge
sources, conversations, a WhatsApp session. Against production it refuses unless
you pass `--allow-production`.

It prints one line per check and exits non-zero if any fail. `--keep` leaves the
test data behind when you want to inspect it.

### What it proves


| Phase          | Checks                                                                                                                                                                                                                           | Why it matters                                                                                                                                                 |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Infrastructure | `/healthz`, `/readyz` deep-checks Postgres + Redis + WAHA, `/metrics` renders business series                                                                                                                                    | A green `/healthz` with a broken database is the failure that looks like success                                                                               |
| Auth           | Owner and admin sign in, wrong password rejected, unauthenticated rejected, **owner cannot reach** `/api/admin/`*                                                                                                                | The 403 is the multi-tenant boundary; if it ever returns 200 the product is broken in the way that matters most                                                |
| Read surface   | 14 owner endpoints answer 200                                                                                                                                                                                                    | Catches a route that broke on a schema change                                                                                                                  |
| Billing        | Catalogue order, **no price leaks through the API**, checkout returns instructions with no gateway, plan change rewrites entitlements from the catalogue, expired cancellation blocks, **a just-failed payment keeps answering** | The grace window is the one nobody would notice was broken until a customer's bot went silent over a card retry                                                |
| Knowledge      | Source created, worker ingests to `ready`, embedded chunks exist, source deletes                                                                                                                                                 | Proves the worker, the queue and the embedding provider are all alive                                                                                          |
| Pipeline       | Unsigned webhook rejected (401), signed one buffered, replayed id deduplicated, group chat filtered, flood rate limited, message persisted and visible in the inbox                                                              | The webhook is the product's front door; signing one by hand exercises tenant resolution, HMAC, the chat filter, dedupe and the limiter with no phone involved |


It restores what it changes — billing state is read before and put back after —
so it is safe to run repeatedly.

### Reading a failure

- **"LLM provider returned 429 (quota)"** — an environment limit, not a defect.
Staging inherits production's provider key by default, so a smoke run can
exhaust the real quota. Give staging its own key (see `.env.staging.example`).
- **"the worker ingested it" fails** — the worker is not consuming. Check
`docker logs qonvo-staging-worker-1`; the classic cause is the scheduler and
worker sharing one arq queue.
- **"platform admin can sign in" skipped** — that password was rotated. Pass
`QONVO_E2E_ADMIN_PASSWORD`, or re-seed.
- Anything in the Auth phase failing is a stop-the-line event.

---



## Part 2 — the manual run, in order

**These steps are chronological and dependent.** Earlier ones set up state the
later ones need, and three of them are destructive if run early. Work top to
bottom.

Order corrections worth knowing, because the obvious order is wrong:

- **Google must be connected before the booking and order checks** — those write
  to a calendar and a sheet that do not exist until then.
- **The recovery drill is last.** It logs the session out, which breaks every
  check above it.
- **Suspend is late, and you must undo it.** A suspended tenant's bot is silent,
  so anything after it would look broken.

Needs: the stack up (`./qonvo-up.sh`), a phone you own, and provider keys.

---

### Stage 1 — Start clean

| # | Do | Expect |
|---|---|---|
| 1.1 | Admin → Tenants → delete each existing tenant | Gone from the list |
| 1.2 | `./scripts/measure-usage.sh` | Tenants 0, and note the WAHA sessions total |

Deleting a tenant is a **hard delete** (see "Is delete really hard?" below).

### Stage 2 — Sign up as a new business

| # | Do | Expect | Covers |
|---|---|---|---|
| 2.1 | Public `/signup`, new business + email you own | Land in the dashboard, signed in | self-serve signup |
| 2.2 | Check the API log for the welcome email | Body logged (`QONVO_EMAIL_PROVIDER=log`) or delivered on SMTP | transactional email |
| 2.3 | Billing page | Trial plan, **14 days left**, entitlements shown | trial + entitlements |
| 2.4 | Settings → onboarding checklist | Steps listed, WhatsApp unticked | onboarding |

### Stage 3 — Teach it, before connecting anything

Knowledge first: the bot has nothing to say until this is done, and ingestion is
async, so starting it now means it is ready by the time the phone is linked.

| # | Do | Expect | Covers |
|---|---|---|---|
| 3.1 | Knowledge → add **pasted text** with checkable facts (hours, refund window) | status → `ready` | text ingest |
| 3.2 | Knowledge → add a **URL** | status → `ready` | URL ingest |
| 3.3 | Knowledge → **upload a file** (.txt, .pdf, .docx) | status → `ready`, **not `error`** | file ingest |
| 3.4 | Settings → persona, tone, business hours (open now), save, reload | Persisted | config |

**3.3 is the one to watch.** File uploads failed with `FileNotFoundError` until
2026-09-05 because the API and worker did not share a volume. If it goes to
`error`, the fix did not reach this environment.

### Stage 4 — Connect the number

| # | Do | Expect | Covers |
|---|---|---|---|
| 4.1 | WhatsApp → scan the QR from the business phone | Status `WORKING` | session provisioning |
| 4.2 | Onboarding checklist | WhatsApp step now ticks | |
| 4.3 | Admin → Fleet | Session listed as working | fleet console |

A brand-new session starts at **warm-up stage 1: 50 sends/day for a week**. Fine
for testing; if you hit the cap the bot goes quiet, which is the cap working.

### Stage 5 — Conversation, from another phone

| # | Send | Expect | Fault if |
|---|---|---|---|
| 5.1 | "what are your hours?" | The answer from **your** knowledge | It invents hours |
| 5.2 | "do you sell aeroplane parts?" | Declines, offers a human; **handoff** in Notifications; owner alert email | It makes something up |
| 5.3 | Roman Urdu: "aap kab khulte hain?" | Reply in Roman Urdu | Answers in English |
| 5.4 | Three messages fast | **One** reply covering all three | Three replies (debounce broken) |
| 5.5 | 25 messages fast | Later ones ignored | It answers all 25 |
| 5.6 | A voice note asking about hours | Understood; voice reply if mode is `match` | Silence |
| 5.7 | A photo + "what is this?" | Describes what is actually in it | Generic reply (vision blind) |

**5.6 note:** the configured TTS (`orpheus-v1-english`) **cannot speak Urdu**. An
English voice reply proves the path works; Urdu voice needs a different provider.

### Stage 6 — Connect Google (before the skills that need it)

| # | Do | Expect | Covers |
|---|---|---|---|
| 6.1 | Integrations → **Connect Google** → consent | Connected; a "Qonvo Bookings" calendar appears in that account | OAuth |
| 6.2 | Pick a spreadsheet via the **Google Picker** | Selected | `drive.file` scope |
| 6.3 | Try typing a spreadsheet id instead | **Fails, by design** — the scope only grants what was picked | |

### Stage 7 — Skills that act

| # | Send | Expect |
|---|---|---|
| 7.1 | "I want to book tomorrow at 3pm" | Booking confirmed; **event in Google Calendar** |
| 7.2 | "I want 2 chicken burgers" | Order taken; row visible in Analytics |
| 7.3 | Something that writes to the sheet | **Row appears in the spreadsheet** |
| 7.4 | "how do I pay?" | Payment details from Settings, verbatim |
| 7.5 | Wait for the booking reminder window | Confirmation + 24h reminder, max 2 |

### Stage 8 — Takeover

| # | Do | Expect |
|---|---|---|
| 8.1 | Reply to the customer **from the business phone** | Bot goes quiet; Inbox shows human-handled |
| 8.2 | Inbox → Take over → send a reply | Arrives from the business number |
| 8.3 | Inbox → Release | Bot answers the next message |
| 8.4 | Wait out the takeover TTL, message again | Bot resumes on its own |

### Stage 9 — Review what it recorded

| # | Do | Expect |
|---|---|---|
| 9.1 | Inbox → open the conversation | Full transcript; voice playable |
| 9.2 | Knowledge → Gaps | 5.2's unanswerable question listed |
| 9.3 | Analytics | Messages, cost, leads/bookings/orders all non-zero |
| 9.4 | Billing | Trial days left, entitlements, plans with a working Choose |
| 9.5 | Team → invite an address you own → accept → set password → sign in | Teammate sees the inbox |
| 9.6 | Team → Export data | JSON downloads with your conversations |
| 9.7 | Account → change password, sign out, sign in | New password works |

### Stage 10 — Admin, and the destructive checks

Everything above must be finished first.

| # | Do | Expect |
|---|---|---|
| 10.1 | Admin → Overview | Tiles populated |
| 10.2 | Admin → System health | Readiness green, tiles live |
| 10.3 | Admin → set the tenant's subscription to a paid plan | Owner's Billing shows it; entitlements change |
| 10.4 | Settings → business hours to a **closed** window → message | One "we're closed" reply, then silence |
| 10.5 | **Undo 10.4** | Bot answers again |
| 10.6 | Admin → **suspend** the tenant → message | Bot silent |
| 10.7 | **Reactivate** | Bot answers again |

### Stage 11 — Recovery drill (last, it unlinks the phone)

| # | Do | Expect |
|---|---|---|
| 11.1 | Phone → WhatsApp → Linked devices → log Qonvo out | Within ~15 min: failed, 3 recovery attempts, one notification |
| 11.2 | Re-scan the QR | Back to `WORKING`, attempt counter reset |

### Stage 12 — Measure it

| # | Do | Expect |
|---|---|---|
| 12.1 | `./scripts/measure-usage.sh` | Real numbers for tokens/reply, storage, WAHA session size |
| 12.2 | Compare to [DEPLOYMENT-AND-COSTS.md](DEPLOYMENT-AND-COSTS.md) | Update any claim that differs |

This is the step that turns the cost model from estimate into fact. In
particular it will show the **first-ever WAHA session size with `fullSync` off**,
which is currently the least-evidenced number in that document.

---

## Is the admin delete really a hard delete?

Yes for the database and for WhatsApp, with one caveat about disk.

**Verified by reading `admin.py:delete_tenant` and by testing on staging:**

| What | Removed? |
|---|---|
| All 23 tenant-scoped tables | **Yes** — explicit `DELETE ... WHERE tenant_id`, no soft-delete flag anywhere |
| The tenant row | Yes |
| Users left with no other membership | Yes (platform admins are skipped, deliberately) |
| Users who belong to another tenant | **No, by design** — they keep that other workspace |
| WAHA session files | **Yes** — `DELETE /api/sessions/{name}` removes the directory. Tested: 124 KB directory present, gone after the call |
| Uploaded knowledge files | **Yes, since 2026-09-05.** Nothing removed them before; that was a privacy leak as much as a disk one |
| Redis keys (dedupe, own-send, rate limits) | Not purged, but all carry TTLs (60s to 24h) and expire on their own |
| MinIO objects | Nothing to remove — media is never copied there |

**The caveat.** Postgres `DELETE` marks rows dead and frees the space **for
reuse**; it does not return it to the operating system, so the database file
does not shrink. For a 12 MB database this is irrelevant. If you want the disk
back:

```bash
docker exec qonvo-postgres-1 psql -U qonvo -d qonvo -c "VACUUM FULL"   # locks tables
```

`./scripts/measure-usage.sh` reports dead tuples so you can see it.

## Known faults



### 1. A provider failure discards the customer's message — FIXED 2026-09-05

**Found 2026-09-04, confirmed on staging, fixed the next day.** Kept here because
the shape of it is worth remembering, and because the regression tests in
`tests/test_pipeline_persistence.py` exist to stop it coming back.

The whole turn runs in one transaction
(`[pipeline.py:611](../backend/app/workers/pipeline.py#L611)` says so in its own
docstring). When the LLM call exhausts its retries, everything rolls back: the
inbound message, the conversation, the handoff row and the owner notification.

Side effects do not roll back. Observed: the worker logged
`[email:log] A customer needs a human` and wrote a DLQ row, while the database
ended with **zero** conversations, messages, handoffs and notifications.

Consequences, in order of seriousness:

1. The owner can receive "a customer needs a human" and find **nothing** in the
  inbox.
2. The customer's message is not recorded anywhere a human will look.
3. Dedupe is Redis-keyed for 24h, so if WhatsApp redelivers that message id it is
  dropped as a duplicate. **The message is then lost for good.**

The DLQ row means ops can see it happened, which is why this is a fault rather
than a disaster.

**The fix**, now in place: the inbound message and the conversation are written
and committed in their own transaction before the LLM is called, leaving only the
reply inside the retried unit. Persistence had to become idempotent at the same
time, because arq retries the whole job and a bare insert would then hit the
`wa_message_id` unique constraint -- which would turn a transient provider blip
into a permanently unanswered customer.

Verified with the quota still exhausted: the e2e smoke run went from 45/2 to
47/0, with the message surviving the 429.

### 2. Integration tests pollute each other

Covered in `[TESTING.md](TESTING.md)` §4: the pg modules share one FastAPI app
and each clears every dependency override on teardown, so results depend on
collection order. **Re-run any failure in isolation before believing it.**

### 3. Staging shares production's LLM quota

`.env.staging` is copied from `.env`, so a smoke run can exhaust the real
quota and leave production answering 429 to real customers. Give staging its own
key before running load through it.

---



## Where we stand

Fill this in as you go; it is the record of what has actually been exercised.


| Area                                     | Automated   | Manual           | Last verified                |
| ---------------------------------------- | ----------- | ---------------- | ---------------------------- |
| Infrastructure, auth, read surface       | ✅ 45 checks | —                | 2026-09-04                   |
| Billing lifecycle                        | ✅           | D6 pending       | 2026-09-04 (API)             |
| Knowledge ingestion (text)               | ✅           | D4 pending       | 2026-09-04                   |
| Inbound pipeline, gates, dedupe, limiter | ✅           | T4, T5 pending   | 2026-09-04                   |
| Grounded reply, handoff                  | —           | T1, T2 pending   | 2026-08-14 (ad hoc)          |
| Voice in and out                         | —           | T6 pending       | 2026-08-14 (owner confirmed) |
| Images to vision                         | —           | T7 pending       | never                        |
| Booking, order, sheets                   | —           | T8, T9 pending   | 2026-07-10                   |
| Takeover and resume                      | —           | T10, T11 pending | 2026-08-14                   |
| Session recovery                         | —           | R1, R2 pending   | 2026-08-18 (forced, live)    |
| Google OAuth                             | —           | 3.1 pending      | 2026-08-15                   |
| Email delivery                           | —           | 3.2 pending      | 2026-08-17 (SMTP)            |
| Payments                                 | n/a         | 3.3 manual path  | no gateway yet               |
| Load and concurrency                     | never       | never            | **never**                    |


The last row is the real gap: nothing has ever been tested under concurrent load.









## Every feature, and how to use or test it


| Feature                        | How to use / test it                                            |
| ------------------------------ | --------------------------------------------------------------- |
| **Grounded replies (RAG)**     | Add knowledge → ask about it on WhatsApp → T1                   |
| **No hallucination + handoff** | Ask something not in knowledge → T2                             |
| **Multilingual**               | Message in Roman Urdu → T3                                      |
| **Voice in / out**             | Send a voice note; Settings → Voice mode → T6                   |
| **Images → vision**            | Send a photo with a question → T7                               |
| **Debounce**                   | Three fast messages → one reply → T4 · automated                |
| **Dedupe / rate limit**        | 25 fast messages → later ones dropped → T5 · automated          |
| **Human takeover**             | Reply from the business phone, or Inbox → Take over → T10, D2   |
| **Business hours**             | Settings → hours → message off-hours → D8                       |
| **Booking + availability**     | "book tomorrow 3pm" → check Calendar → T8                       |
| **Orders**                     | "I want 2 burgers" → Analytics → T9                             |
| **Leads**                      | Bot asks for contact details when relevant → Analytics          |
| **Sheets read / write**        | Integrations → pick a sheet → 3.1                               |
| **Payment details**            | Settings → payment details → ask "how do I pay?"                |
| **Booking reminders**          | Create a booking; scheduler sends confirm + 24h reminder        |
| **Knowledge (text/file/URL)**  | Knowledge → Add → wait for `ready` · automated                  |
| **Answer gaps**                | Knowledge → Gaps after T2 → D4                                  |
| **Inbox**                      | `/inbox` → open a chat → D1–D3                                  |
| **Settings**                   | `/settings` → change, save, reload → D7                         |
| **Analytics**                  | `/analytics` → D5                                               |
| **Billing + plans**            | `/billing` → Choose a plan → D6 · automated                     |
| **Team seats**                 | Team → invite → accept → 3.2                                    |
| **Data export**                | Team → Export data · automated                                  |
| **Onboarding checklist**       | Settings card, ticks as you connect things                      |
| **Notifications**              | Bell icon; populated by T2                                      |
| **Password self-service**      | Account → change; Login → forgot → 3.2                          |
| **Signup + 14-day trial**      | `/signup` on the public URL                                     |
| **Quotas / entitlements**      | Set a plan, check the cap on `/billing` · automated             |
| **Number warm-up**             | New session → 50/day week 1, 150 week 2                         |
| **Session auto-recovery**      | Log Qonvo out from the phone → R1, R2                           |
| **Admin: tenants**             | `/admin/tenants` → suspend → D9                                 |
| **Admin: fleet**               | `/admin/fleet` → D10                                            |
| **Admin: health**              | `/admin/health` → D11                                           |
| **Admin: mark paid**           | `PUT /api/admin/tenants/{id}/subscription` → 3.3 · automated    |
| **Metrics / Grafana**          | `/metrics`; Grafana on :3003 · automated                        |
| **Tenant isolation (RLS)**     | Owner token on an admin route → 403 · automated                 |
| **Staging**                    | `./qonvo-staging.sh up` → :3012 shows a **Staging** badge → D12 |
| **Backups**                    | `crontab -l`; nightly 03:15, 672 KB/run                         |
| **CI**                         | Pushes to `dev`/`main` (once you push)                          |
| **Releases**                   | `./scripts/release.sh 0.10.0`                                   |


Full detail, including the numbered checks above and a standing record of what's been verified versus never, is in [docs/E2E-LIVE-TEST-PLAN.md](vscode-webview://004uuned7ooet9fhc0g5rur6dr90qqv5vjokmppo0l4bc00plaqh/docs/E2E-LIVE-TEST-PLAN.md).