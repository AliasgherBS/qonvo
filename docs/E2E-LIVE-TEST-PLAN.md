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



## Part 2 — manual, with a phone

Needs: the stack up, a WhatsApp number linked, and provider keys (Gemini for
text; a Groq or OpenAI key for voice). Do this on **production** with a number
you own, because staging's WAHA has no linked phone.

Record the result in the table at the bottom.

### 2.1 Setup, once

1. `./qonvo-up.sh`, then sign in at [http://localhost:3002](http://localhost:3002) as the owner.
2. **Knowledge** → add a source with facts you can check, e.g. *"We are open
  Monday to Saturday, 9am to 7pm. Closed Sunday. Refunds within 14 days."*
   Wait for status `ready`.
3. **WhatsApp** → scan the QR from the business phone. Wait for `WORKING`.



### 2.2 The conversation checks

Message the business number from a **different** phone.


| #   | Send this                                            | Expect                                                                         | Fault if                                               |
| --- | ---------------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------ |
| T1  | "what are your hours?"                               | The answer from your knowledge, not a generic one                              | It invents hours, or says it does not know             |
| T2  | "do you sell aeroplane parts?"                       | It declines and offers a human; a **handoff** appears in Notifications         | It makes something up. Grounding is the core promise   |
| T3  | Same question in Roman Urdu ("aap kab khulte hain?") | Reply in Roman Urdu                                                            | It answers in English                                  |
| T4  | Three messages in a row, fast                        | **One** reply covering all three                                               | Three separate replies (debounce broken)               |
| T5  | 25 messages as fast as you can                       | Later ones ignored; `rate_limited` in the API log                              | It answers all 25 (your bill is uncapped)              |
| T6  | A voice note asking about hours                      | It understands and answers. With voice mode `match`, replies with a voice note | Silence, or a reply about not understanding audio      |
| T7  | A photo of something with "what is this?"            | It describes what is actually in the image                                     | A generic reply, meaning the vision path is blind      |
| T8  | "I want to book tomorrow at 3pm"                     | A booking is created; check Google Calendar                                    | Nothing in the calendar (needs part 3.1)               |
| T9  | "I want 2 chicken burgers"                           | An order row; check **Analytics**                                              | No order recorded                                      |
| T10 | Reply to the customer **from the business phone**    | The bot goes quiet; the conversation shows as human-handled in **Inbox**       | The bot keeps replying, or silences itself permanently |
| T11 | Wait out the takeover TTL, message again             | The bot resumes                                                                | It stays silent forever                                |




### 2.3 Dashboard checks


| #   | Do this                                                                  | Expect                                                              |
| --- | ------------------------------------------------------------------------ | ------------------------------------------------------------------- |
| D1  | **Inbox** → open the conversation                                        | Full transcript, voice playable                                     |
| D2  | **Inbox** → Take over, send a reply                                      | It arrives on the customer's phone from the business number         |
| D3  | **Inbox** → Release                                                      | The bot answers the next message                                    |
| D4  | **Knowledge** → Gaps                                                     | T2's unanswerable question is listed                                |
| D5  | **Analytics**                                                            | Message counts, cost and any leads/bookings/orders are non-zero     |
| D6  | **Billing**                                                              | Plan, entitlements, and the plans list with a working Choose button |
| D7  | **Settings** → change the persona, save, reload                          | It persisted                                                        |
| D8  | **Settings** → set business hours to a closed window, message the number | One "we're closed" reply, then silence                              |
| D9  | Sign in as admin → **Tenants** → suspend the tenant, message the number  | The bot is silent. Reactivate; it answers again                     |
| D10 | Admin → **Fleet**                                                        | The session shows `WORKING`                                         |
| D11 | Admin → **System health**                                                | Readiness badges green, tiles populated                             |
| D12 | Topbar on staging (:3012)                                                | A **Staging** badge. Production (:3002) shows none                  |




### 2.4 The recovery check, worth doing once


| #   | Do this                                                 | Expect                                                                                                                        |
| --- | ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| R1  | On the phone: WhatsApp → Linked devices → log Qonvo out | Within ~15 min the session shows failed, recovery attempts stop at 3, and one notification appears saying a re-scan is needed |
| R2  | Re-scan the QR                                          | It returns to `WORKING` and the attempt counter resets                                                                        |


---



## Part 3 — external accounts



### 3.1 Google (Calendar and Sheets)

1. **Integrations** → **Connect Google** → consent.
2. Expect a "Qonvo Bookings" calendar to be created in that Google account.
3. Pick a spreadsheet through the Google Picker (a typed id **will** fail: the
  `drive.file` scope only grants what the owner picked, by design).
4. Re-run T8 and T9 and confirm the calendar event and the sheet row.
5. Disconnect Sheets and confirm **Calendar still works** — Google's revoke kills
  the whole grant for a client id, so this is guarded on purpose.



### 3.2 Email

1. **Team** → invite an address you own → the invitation arrives → accept it →
  set a password → sign in → the inbox is visible.
2. **Forgot password** → the reset link arrives and works once (a second use must
  fail).
3. Trigger T2 and confirm the handoff alert email arrives.

With `QONVO_EMAIL_PROVIDER=log` nothing is actually sent; the message body is in
the API log instead. That is the correct staging setting.

### 3.3 Payments

Not testable yet: there is no merchant-of-record account. What exists is the
manual path, which **is** testable today:

1. Admin → `PUT /api/admin/tenants/{id}/subscription` with a plan.
2. The owner's **Billing** page shows the plan and the entitlements it grants.
3. The message quota on the pipeline matches that plan.

---



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