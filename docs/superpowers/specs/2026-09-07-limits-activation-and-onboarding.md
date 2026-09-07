# Limits, activation and onboarding

**Status:** §1-§6 and §8 implemented 2026-09-07. §7's adapter is built; its
account setup is not, and cannot be until the Polar account exists.
**Owner decisions:** all answered bar the legal name. See §9 for what was
decided and where this document turned out to be wrong.

Seven workstreams. They are ordered by dependency, not by importance: §1 and §2
must land before §7 can price anything honestly, and §3 changes what a new
tenant experiences on day one.

Each part is independently implementable. An agent can take one and ship it.

---

## 0. Why this exists

Three things are true today and all three cost money or credibility:

1. **Voice is ungated.** `app/billing/plans.py` entitlements are only
   `monthly_message_quota` and `seats`. Any tenant can set `voice_reply_mode` to
   `always` and multiply their cost by five on the cheapest plan. Voice is 54-74%
   of per-tenant AI cost (`docs/DEPLOYMENT-AND-COSTS.md` §6.5), and the product
   spec already calls it a value-added service rather than base.
2. **Knowledge and prompt inputs are unbounded.** Nothing caps upload size, total
   knowledge per tenant, or the length of `custom_instructions`, which is paid
   for on *every single turn*.
3. **A new tenant goes live instantly and ungrounded.** Signup, scan the QR code,
   and the bot answers real customers from an empty knowledge base. That is the
   worst possible first impression of the product, and the owner never consented
   to it.

---

## 1. Voice allowance

### 1.1 The unit

**Meter in characters. Display minutes.**

Providers bill TTS per character and STT per second, so characters are what the
system can actually count. Minutes are what an owner understands. Convert with
one named constant, defined once:

```
CHARS_PER_VOICE_MINUTE = 1000   # ~150 wpm, ~6 chars/word
```

Every user-facing surface says "minutes". Every stored counter is characters (or
seconds for STT). Do not let minutes into the database.

### 1.2 The allowance per plan

Add a third entitlement key alongside `monthly_message_quota` and `seats`:

| Plan | `monthly_voice_minutes` |
|---|---:|
| `trial` | 5 |
| `starter` | 5 |
| `growth` | 20 |
| `scale` | 100 |

Entitlements are **derived** from the catalogue by `apply_plan`, so adding the
key there is enough; do not write it onto tenants by hand.

### 1.3 Why those numbers are affordable

At the doc's recommended TTS (OpenAI `tts-1`, $15/1M chars = $0.015/min) and the
measured text floor of $0.49 per 1,000 messages:

| Plan | Price | Messages | Text cost | Voice | Voice cost | Total | Gross |
|---|---:|---:|---:|---:|---:|---:|---:|
| Starter | $10 | 1,000 | $0.49 | 5 min | $0.08 | $0.57 | **94%** |
| Growth | $18 | 5,000 | $2.45 | 20 min | $0.30 | $2.75 | **85%** |
| Scale | $30 | 20,000 | $9.80 | 100 min | $1.50 | $11.30 | **62%** |

Worst case, on the most expensive Urdu-capable TTS (ElevenLabs Flash, $0.05/min)
with every tenant at full quota:

| Plan | Total cost | Gross |
|---|---:|---:|
| Starter | $0.74 | 93% |
| Growth | $3.45 | 81% |
| Scale | $14.80 | **51%** |

Still profitable at the floor, before the merchant of record's ~5%. **The
proposed 5/20/100 ladder is safe at $10/$18/$30.** Compare to today, where an
unlimited-voice Scale tenant costs ~$54 against $30 revenue: a loss.

### 1.4 Metering

Voice is currently metered somewhere in the pipeline (§ voice landed in commit
`1ad91b7`) but not against an entitlement and not visibly. Required:

- **One counter per tenant per billing period**, incremented on both legs:
  - voice **in**: STT seconds, converted to chars via the constant
  - voice **out**: TTS characters, exactly as sent to the provider
- **Recommendation: count both legs against one allowance.** "Voice minutes"
  naturally means voice handled in either direction, and STT is roughly 30x
  cheaper than TTS, so out dominates regardless. One number is easier to explain
  than two.
- Persist to the same place message usage lives, so the gate and the dashboard
  read one source. Do not add a parallel store.
- Record enough to bill from later: tenant, period, direction, characters,
  provider, model, and cost. The existing per-message cost recording is the
  precedent to follow.

### 1.5 The gate

When the allowance is exhausted, **degrade, do not fail.** The bot keeps working;
it just replies by text.

- Reply as text, and say so once per period: *"I can keep answering by text.
  Voice replies are paused until your plan renews."*
- Dedupe that notice with `meta={"auto_reply": "voice_quota"}`, exactly as
  `business_hours` dedupes per window in `app/workers/pipeline.py`.
- Notify the owner once per period, and surface it on the billing page.
- **Never drop the reply.** A silent bot is the failure mode this codebase has
  already been burned by twice.

Also cap a single utterance so one long voice note cannot eat the month: reuse
or extend the existing audio-size cap.

---

## 2. Knowledge and prompt caps

### 2.1 Why the prompt ones matter most

`custom_instructions` is in the system prompt on **every turn**. The Depilex
tenant runs 1,821 chars, about 455 tokens. Unbounded, a tenant pasting 50,000
chars pays ~12,500 tokens per reply: roughly **$1.88/month** of pure waste on one
tenant at Gemini input rates, and materially worse answers, because the real
instructions drown.

RAG context is already capped at `rag_context_max_tokens = 2000`. The prompt
fields are the hole.

### 2.2 Proposed caps

All figures are proposals. Adjust before implementing; the reasoning matters
more than the number.

**Prompt fields** (enforced in `ConfigUpdateRequest`, `app/api/config.py`, with
Pydantic `max_length` so the API rejects rather than truncates):

| Field | Cap | Why |
|---|---:|---|
| `custom_instructions` | 2,000 chars | ~500 tokens, every turn. Twice what a good tenant needs |
| `persona` (free text via API) | 500 chars | The dropdown covers most cases |
| `business_name` | already 255 | no change |
| `payment_details` | 1,000 chars | sent verbatim to customers |

**Knowledge** (enforced at the API and re-checked in the ingestion worker, since
a file arrives in two steps):

| Limit | Cap | Why |
|---|---:|---|
| Single file upload | 10 MB | A 10 MB PDF is already thousands of chunks |
| Single text entry | 50,000 chars | About 20 pages pasted |
| Sources per tenant | 25 / 50 / 100 by plan | Bounds the ingestion queue |
| Total knowledge chars per tenant | 500k / 2M / 10M by plan | This is the real storage and embedding cost |

Total knowledge is the one that actually bounds spend: every chunk is an
embedding row in pgvector and is re-embedded on re-crawl.

### 2.3 Enforcement rules

- Reject at the **API boundary** with a message naming the limit and the current
  value: *"Custom instructions are limited to 2,000 characters. This is 3,140."*
  Never truncate silently.
- The ingestion worker must **re-check** total-chars before embedding, because
  the total can be exceeded by a file whose size passed the per-file check.
- Existing tenants over a new cap must not break. Grandfather on read, enforce on
  write.

### 2.4 Placeholder and guidance text

The user asked for this explicitly, and it is the cheapest quality win in the
list. Every prompt field gets placeholder text that teaches by example, plus a
live character counter showing `used / cap`.

`custom_instructions` placeholder, for instance:

```
Rules your rep must always follow. Be specific and short.

Example:
- Never quote a price. Say it depends on the branch and offer to check.
- If you do not know, say so and offer to pass the customer to the team.
- Match the customer's language. Reply in Roman Urdu if they write Roman Urdu.
```

`fixtures/depilex/persona.md` is a worked example of instructions that survived a
live grounding test. Mine it for the placeholder copy.

Show the counter turning amber at 80% and red at 100%. Do not disable save;
disable it only when over.

---

## 3. Activation: the bot starts off

### 3.1 The problem

Today: signup, connect WhatsApp, and the rep answers live customers from an empty
knowledge base. Nobody agreed to that.

### 3.2 Required behaviour

- **A new tenant's rep is inactive.** Add an explicit tenant-level active flag.
  Do not overload the per-conversation takeover states (`bot_active`,
  `paused_by_owner`, `needs_human`) — that machinery is per conversation and
  works; this is a different, account-level switch.
- While inactive, inbound messages are **received, stored and visible in the
  inbox**, and the bot does not reply. The owner can still answer by hand.
- **Activation is an explicit action** with a readiness check in front of it.

### 3.3 Readiness check

Before the toggle can be turned on, require:

| Requirement | Rule |
|---|---|
| WhatsApp connected | session exists and is authenticated |
| Grounding present | at least one knowledge source at status `ready`, **or** non-empty `custom_instructions` |
| Business name set | not null, not the seeded default |
| Tested once | at least one inbound message answered in a test, **recommended not required** |

Grounding is the load-bearing one. `custom_instructions` counts because a tenant
may legitimately run on rules alone, as the Depilex test proved.

**If a requirement is unmet, do not silently block.** Show what is missing, link
straight to the page that fixes it, and let the owner override with a typed
confirmation and a plain warning: *"Your rep will tell customers it does not know
the answer to most questions. Continue anyway?"* Their number, their call.

### 3.4 The toggle

A first-class control, not buried in settings. The owner needs it for the case
they described: taking the number back for a while.

- Visible on the dashboard home and on Settings.
- Two states, in the owner's language: **Rep is answering** / **Rep is paused**.
- Pausing is instant, needs no confirmation, and is reversible.
- Pausing shows what it means: *"Messages will still arrive in your inbox. You
  answer them yourself until you switch this back on."*
- Log both transitions to `audit_log`.

### 3.5 Interaction with everything else

- Trial expiry, past-due and suspension already gate replies through
  `service_state`. The active flag is **additional**, not a replacement. Both
  must pass.
- Do not let activation flip the flag back on by itself after a pause.

---

## 4. Usage visibility

Currently neither the owner nor the admin can see voice usage at all, and message
usage is thin.

### 4.1 Owner, on the billing page

Three meters, same shape, all showing `used / allowance` and a bar:

| Meter | Detail |
|---|---|
| **Messages** | `1,240 / 5,000 this month` + reset date |
| **Voice minutes** | `12 / 20 this month` + reset date |
| **Trial days left** | only while on trial: `9 days left` + what happens at zero |

Plus, where relevant: seats used of seats allowed, knowledge sources used of
allowed, and total knowledge used of allowed.

State must be legible at a glance, not just numeric: amber at 80%, red at 100%,
and at 100% a line saying exactly what degrades (voice pauses; messages stop).

### 4.2 Admin, per tenant

The ops console needs the same numbers per tenant plus a fleet view:

- Per tenant: messages, voice minutes, seats, knowledge, all against allowance;
  plan; trial end; `service_state`; **active/paused**.
- Fleet: tenants near or over any limit, sorted worst first. This is the screen
  that catches a runaway tenant before the invoice does.
- Voice cost per tenant for the period, from the metering in §1.4.

### 4.3 One source of truth

Owner and admin must read the same computation. Put the "usage against
entitlement" logic in one service function and call it from both. Two
implementations will diverge, and the admin one will be the wrong one.

---

## 5. Hide the model selector

Business advanced settings currently lets a tenant choose a different LLM. Hide
it. Not a feature we want to support now; may return later.

- Remove the control from the UI. **Keep `llm_provider` / `llm_model` in the API
  and the database** — the per-tenant override is genuinely useful for support
  and for pinning a tenant during an incident, and `resolve_llm` already prefers
  `providers["llm"]`.
- Leave it settable by an admin, or by API only.
- Do not migrate away existing values.

---

## 6. Trial length: one source of truth

The trial is **14 days or 300 messages, whichever comes first**. Some surfaces say
a month. Fix by making one value authoritative and deriving every mention.

An agent should grep for `14`, `month`, `30 day`, `two weeks`, `fortnight` across
at least: the trial length used by signup and `apply_plan`; `plans.py`;
`legal/TERMS.md`; `dashboard/lib/legal.ts`; the marketing pricing and FAQ
components; `dashboard/public/llms.txt`; `app/services/email_templates.py`
(the `welcome` template); and the billing page.

Known correct today: `llms.txt` and the marketing pricing component both say 14
days. Treat those as the intended value and correct the rest.

Then add a test that fails if the trial length appears as a literal anywhere but
its definition.

---

## 7. Polar integration

Docs: <https://polar.sh/docs/introduction>. Sandbox: `sandbox.polar.sh`, API
`sandbox-api.polar.sh/v1`. Production tokens do not work in sandbox and vice
versa.

### 7.0 What is built

`PolarProvider` is implemented, registered and covered by 39 tests. What is not
built is the account setup in §7.3, which cannot be done from a repository.

The signature check is the security boundary: it is the only thing between a
stranger and granting themselves the Scale plan. Signatures in the tests are
generated the way Polar generates them rather than recorded, so they fail if the
algorithm drifts and not merely if a fixture goes stale. Bypassing verification
fails nine of them.

Two details worth knowing before wiring it up.

**Polar changed its signing scheme on 2026-09-08.** A secret from before that
date is a raw HMAC key; one from after is a Standard Webhooks `whsec_` secret.
The adapter tries both derivations and accepts either, because asking an
operator which side of a date their account was created on is a question whose
wrong answer is a 401 that reads exactly like a bad secret.

**`subscription.canceled` does not mean stopped.** It fires when a cancellation
is *scheduled*, and service continues to the period end, which `service_state`
already handles. `subscription.revoked` means stopped. Treating them alike would
cut a paying customer off early.

### 7.1 Secrets

The owner supplied an organization access token (`polar_oat_...`) in chat.
**It must not be committed, and it should be rotated once the integration works**,
because it has been in a conversation log.

```bash
QONVO_BILLING_PROVIDER=polar
QONVO_POLAR_ACCESS_TOKEN=<from .env, never the repo>
QONVO_POLAR_WEBHOOK_SECRET=<from the Polar dashboard>
QONVO_POLAR_SERVER=sandbox        # or production
QONVO_BILLING_PRICE_MAP='{"<polar_price_id>":"starter", ...}'
```

`.env` is gitignored; only `.env.example` is tracked. Add the keys there with
empty values.

### 7.2 What to build

A `PolarProvider` in `app/billing/providers/`, registered in `registry.py`,
implementing the same two methods `ManualProvider` does. `manual.py` is the
reference; the seam already exists and was deliberately proven by a second
implementation.

- `checkout(tenant_id, plan_key) -> Checkout` — create a Polar checkout session
  and return its **url**. Pass the tenant id as metadata so the webhook can
  resolve it without a lookup table.
- `parse_event(headers, raw) -> BillingEvent | None` — **verify the webhook
  signature before parsing**, and return `None` for anything not ours. The
  existing `billing_events` table is an idempotency ledger precisely because
  merchants of record retry; use it.
- Map Polar price ids to plan keys through `settings.billing_price_map`, which
  already exists for this.

Cover at minimum: subscription created, updated, cancelled, and payment failed.
Past-due already has a 7-day grace in `service_state`; wire failures to it rather
than inventing a second path.

### 7.3 What the owner must do in Polar

Nothing here can be scripted before the account exists.

1. Sign up, then **submit for verification immediately** — it takes ~2 weeks and
   runs in parallel with the build.
2. **Add social links** in Settings → General. Polar asks for these at approval.
3. Create three products with monthly and annual prices:

   | Product | Monthly | Annual (2 months free) |
   |---|---:|---:|
   | Starter | $10 | $100 |
   | Growth | $18 | $180 |
   | Scale | $30 | $300 |

   Figures are provisional and changeable later from the dashboard, with no code
   change: prices deliberately live with the merchant of record, never in this
   repo (`plans.py`). Existing subscribers grandfather onto the old price when it
   changes, which matters only once there are subscribers.
4. Copy each **price id** into `QONVO_BILLING_PRICE_MAP`.
5. Set the webhook to `https://api.qonvo.org/webhooks/billing/polar` and copy the
   signing secret.
6. Have a **screen recording** of free → upgrade → pay → access ready. Reviewers
   ask to see the journey, which is why §7.2 has to work before approval, at
   least in sandbox.

### 7.4 Legal, before approval

`legal/TERMS.md` line 4 still reads
`**Provider:** _[Legal entity name — to be filled once formalized]_`.

"Qonvo" alone is a product name, not a legal entity. With nothing registered the
seller is a natural person, so this should read **"<legal name>, trading as
Qonvo"** and match whatever Polar's KYC verifies. A Terms page naming an entity
that does not exist, against KYC naming a person, is the mismatch a reviewer
catches.

---

## 8. Onboarding

Existing onboarding is thin. Replace it with a real guided first run.

### 8.1 A checklist, not a carousel

The unskippable part is a **persistent checklist** on the dashboard home, alive
until complete, each item deep-linking to the page that satisfies it:

1. Connect your WhatsApp number
2. Add what your rep should know
3. Set how it should sound
4. Send it a test message
5. **Turn your rep on**

Item 5 is §3's activation gate, so onboarding and activation are the same
journey rather than two competing ones. Show progress as `3 of 5`. Let it be
dismissed and re-opened from a help menu; never lose it permanently.

### 8.2 The tour

A product tour over the real UI, as the user asked for: a spotlight on an
element with a short explanation, four or five steps, skippable, shown once and
resumable.

Cover the inbox, knowledge, behaviour, and the active/paused toggle. Keep it to
one sentence per step. Persist "seen" per user, not per tenant, so a newly
invited teammate gets it too.

### 8.3 Empty states do the same job

Every screen a new tenant lands on empty should say what to do there, not just
"no data". The knowledge page with zero sources is the most valuable empty state
in the product: it is where a rep becomes useful.

---

## 9. Decisions, as made

| Decision | Answer |
|---|---|
| **Final prices** | Not in code, and never will be: they live with the merchant of record. A test now fails if a currency symbol reaches the welcome email |
| **Voice: one allowance or two** | **One**, as recommended |
| **Knowledge caps** | **Repitched. This document was wrong** -- see below |
| **Override on activation** | **A plain on/off toggle.** No typed confirmation, no readiness gate. Readiness is shown as links to the pages that fix each gap, and never blocks the switch |
| **Legal name for the Terms** | **Still open.** Blocks Polar approval, not the build |
| **Trial: 14 days** | Confirmed, and the premise was wrong -- see below |

### Where this document was wrong

**§2 priced total knowledge as a per-turn cost.** It is not. Retrieval means
only the relevant chunks reach a prompt, so a large corpus costs storage and a
one-off embedding and never makes a reply more expensive. `knowledge_chars` went
*up*, to 2M/5M/15M, with sources at 50/150/400.

The genuinely scarce resources got their own bounds rather than being implied by
that one. Per-file dropped from 10 MB to 5 MB, because a large document does not
cost more to answer from, it blocks the ingestion queue behind one slow parse
while every other tenant waits. And `knowledge_upload_bytes` (50/150/500 MB) is
new, because raw uploads are kept after ingestion so re-ingestion stays possible
when chunking or the embedding model changes, which left the disk as the one
thing nothing bounded.

**§6 expected surfaces claiming "a month".** There were none; every mention
already said 14 days. The real problem was that the number was retyped in seven
places while the value lives in Python, so `dashboard/lib/plan.ts` mirrors it
and a backend test fails when the mirror drifts or anyone retypes the literal.

**§1's unit advice was declined.** It asked for metering in characters.
`usage_counters.voice_seconds` already exists and already normalises both legs
into one unit, so characters would have meant a migration, a second unit for the
inbound leg, and a lossy conversion between them. Seconds convert to minutes
exactly, and the concern behind the advice still holds: nothing stores a minute.

### Two bugs the work exposed

**The upload route read whole files into memory.** `await file.read()` with no
size check anywhere, so a single large upload was an availability problem rather
than a cost one. Now read in chunks, stopping one chunk past the cap.

**`knowledge_chars` measured the wrong table.** Found by reading the live fleet
endpoint: a tenant showed 2 sources and 0 characters against 7,775 genuinely
stored. `sources.content` is NULL for anything uploaded or fetched, so the cap
would not have bound at all on file-based knowledge. Now measured from
`knowledge_chunks`, which is also what actually occupies pgvector.

Worth noting the pattern: both times, building the *visibility* for a limit is
what revealed the limit was measuring the wrong thing.

---

## 10. Suggested order

_All done except §7's account setup. Kept for the record._


1. **§6 trial discrepancy** — smallest, and it is a correctness bug in customer-facing copy
2. **§5 hide the model selector** — one UI change
3. **§2 caps** — bounds cost immediately, no dependencies
4. **§1 voice allowance + metering** — the biggest cost exposure
5. **§4 visibility** — needs §1 and §2 to have something to show
6. **§3 activation** — changes the new-tenant path
7. **§8 onboarding** — subsumes §3's checklist, so it comes after
8. **§7 Polar** — parallel from day one, since approval takes ~2 weeks

§1 through §4 are the ones that stop money leaking. §3, §7 and §8 are what make
the product sellable.
