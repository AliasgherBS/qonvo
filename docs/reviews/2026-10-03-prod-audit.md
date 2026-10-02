# Production audit — 3 October 2026

Driven against `qonvo.org` and `api.qonvo.org` with a real browser and the live API,
signed in as the owner of `test01` and as a tenant created for the purpose.
Production was released to **v0.13.0** immediately before the run.

Legend: **[F]** fault · **[R]** retracted (my test was wrong, the product is fine) · **[G]** verified good

## 0. Stop the line - the production number is served by two stacks at once

A five-message conversation was sent to the live number. Six replies came back. Reading
the API alone, I concluded the product was dropping replies, silencing itself and losing
analytics. **That was wrong, and the logs say so.** What follows is the corrected
account, and the real finding is more serious than the one I reported first.

### [F] P0 - Critical. The same live number is linked to production AND a developer laptop

```
production  :  session test01-b9a90901   number 923194505305   WORKING
this laptop :  session test01-b9a90901   number 923194505305   WORKING
```

Same number, same session name, two independent stacks, both receiving every customer
message and both answering.

The worker logs tell the whole story. Production:

```
20:37:07  sent text via gateway
20:37:28  conversation paused (paused_by_owner) - no reply
20:37:56  conversation paused (paused_by_owner) - no reply
20:38:00  conversation paused (paused_by_owner) - no reply
20:38:30  transcribed voice fragment (54 chars, 4s reported by provider)
20:38:30  conversation paused (paused_by_owner) - no reply
20:39:32  conversation paused (paused_by_owner) - no reply
```

The laptop, in the same minutes:

```
20:37:11  sent text via gateway
20:37:35  sent text via gateway
20:38:02  sent text via gateway
20:38:11  sent text via gateway
20:38:45  sent VOICE via gateway      <- the 47-second reply
20:39:39  sent text via gateway
```

One reply from production, six from the laptop. Seven in total, which is exactly what
reached the phone.

**What this means, in order of seriousness:**

1. **A real business's customers are being answered by a development machine** - on dev
   configuration, dev provider keys, and a database nobody operates.
2. **Production has silenced itself on that number.** It sees the laptop's sends as
   someone else replying from the business line and stands down. That is section 5.5
   working exactly as designed; it is defending against the wrong thing because the wrong
   thing is real.
3. **The owner's production inbox and analytics are missing almost everything.** Six of
   seven turns were handled by the laptop and written to the laptop's database. The
   production record is accurate about what production did, and useless as a record of
   what the business said.
4. **Customers get duplicate replies** whenever both stacks answer, which is what happened
   to the first question.
5. The laptop's stack is on an **older schema** - its `messages` table has no voice
   columns at all - so it is not merely a second copy, it is a second, older copy.

**This is the thing to fix before anything else**, and the fix is to unlink the number
from the local WAHA, not to change any code.

### Four findings I reported and am withdrawing

I wrote these from the API before reading the logs. Each was the dev stack's behaviour
being attributed to production. Recorded rather than deleted, because the method failure
matters more than the findings did: **an API read alone could not distinguish "the
product is broken" from "something else is answering", and I asserted the first.**

| Withdrawn | What I claimed | What was actually true |
|---|---|---|
| ~~C1~~ | 6 replies delivered, 1 stored - persistence is dropping outbound | Production sent exactly 1 and stored exactly 1. Its record was correct throughout. |
| ~~C2~~ | The conversation self-pauses with no human action; section 5.5 is failing | It paused because another sender really was replying from that number. The protection worked. |
| ~~C5~~ | The voice note got no reply | It got a 47-second voice reply, from the laptop, at 20:38:45. |
| ~~C6~~ | Duplicate reply means arq retried after a failed write | Two stacks each answered once. |

`C3` (analytics reporting 1 message where 7 arrived) falls with them: production counted
the one turn it actually handled. It was right.

### [?] C4 - Unverified. Inbound voice duration may not be recorded

Production reports `voice.inbound: count 6, seconds 0` over 30 days, and the worker
logged `4s reported by provider` for today's note. But `voice_seconds_in` lives on
`usage_counters` and is written at `pipeline.py:927`, past the point where today's note
returned early on the paused conversation - and the other five notes predate migration
`0019_voice_seconds_in`. **So there is no evidence either way.** It needs one voice note
on an unpaused conversation to settle, and it matters because generated voice is what the
plan meters.

---

## 8. Second pass - what was fixed, and what the fixing found

Everything in sections 1 to 7 was a first pass. This section is the work that
followed, in the order it was done.

### Resolved: P0, the number served by two stacks

The local WAHA session was stopped, and the conversation it had parked was
released:

```
POST /api/conversations/{id}/release  ->  200 {"state": "bot_active"}
```

All five conversations on the tenant are `bot_active`, so no real customer chat
was left stuck. Production is now the only stack answering that number. The
**real WhatsApp retest is still outstanding** and is the last thing to do.

### Shipped

| | What | Where |
|---|---|---|
| C9 | `/readyz/deep`'s own query was invalid SQL, found by the probe itself | #81 |
| F2 | The plan picker names a price, read from the provider rather than copied into `plans.py` | #76 |
| F3 | `change-plan`, `cancel` and `resume` answer 409 or 502 instead of 200 | #76 |
| F4 | The trial banner links to the plans it used to send people past | #76 |
| P2 | Database pools sized explicitly per process, instead of 90 possible connections against a limit of 100 | #78 |
| P1 | `max_jobs` named rather than inherited from arq's source | #78 |
| P4 | `/readyz/deep`, which asks whether the product can actually answer | #78 |
| - | A UI regression suite, per module, not on every push | #77 |
| C7 | Adding a website failed for almost every website | #79 |

On **F2**, the price is read from Polar rather than added to `plans.py`, whose
own docstring says prices deliberately do not live there. The audit proved the
point: the Polar products still describe 20 voice minutes on a plan that grants
180. A third copy would have recreated F1 facing the other way.

On **P4**, the deep checks are a separate route on purpose. The deploy workflow
greps `/readyz` for `"status":"ok"` and rolls back when it does not find it, so
a tenant mid-rescan must not be able to fail a release.

### [F] C7 - High. Adding a website failed for almost every website

Found by testing the areas the first pass never touched. Every URL tried came
back `error`:

```
httpx.DecodingError: Error -3 while decompressing data: incorrect header check
  url_guard.py:195 in fetch_public_url
```

`aiter_bytes()` yields bytes httpx has **already** decompressed, and the
response rebuilt around them carried the original headers, still announcing
`content-encoding: gzip`. httpx then decompressed the decompressed body.

Compression is the default on essentially every host, so one of the three ways
a tenant teaches their rep anything -- and the one on the onboarding checklist
-- was broken for essentially every website. It failed quietly: the row sat at
`error` with no reason an owner could act on.

### The untouched half, swept

Against a tenant created for the purpose, so no live tenant was written to.

| [G] | Verified |
|---|---|
| Pasted knowledge ingests to `ready`, and the worker picks it up | pass |
| Knowledge usage counts against the plan and reports every meter | pass |
| Behavior config saves and reads back, then restores | pass |
| A stale config version is refused with `409` and a human message | pass |
| All eight skills are listed with their gating | pass |
| Team reads; an invitation is created and revoked | pass |
| Re-inviting the same address **replaces** the pending invite rather than adding one | pass |
| Tenant data exports | pass |
| `/api/admin/*` refuses a plain owner with `403`, three for three | pass |

### Three more findings I checked and withdrew

Checking first is now the habit, after section 4.

| Withdrawn | Why |
|---|---|
| "Duplicate invitations are not refused" | Two 201s, but never two *pending*. Re-inviting replaces. H2 holds. |
| "A stale version is not refused" | I sent 5,000 characters of instructions, so it died on the 2,000 cap before the version was ever checked. |
| "Staging is serving no JavaScript" | It was mid-rebuild, serving the HTML fallback for old chunk URLs. Same class as the deploy 502. |

### [F] C8 - Medium. Staging can serve a new frontend against a stale backend

The first run of the new UI suite failed on cost leakage against staging, and
the cause was staging itself: its **dashboard rebuilds automatically and its
API, worker and scheduler containers do not**. Staging's API container was three
days old and still shipped `cost`, fixed in v0.13.0 and live on production.

A staging environment that silently mixes versions will keep producing findings
that are about staging rather than about the code. It is now in the suite's
README, and `./qonvo-staging.sh up` is the fix.

---

## 1. The billing findings, worst first

### [F] F1 — Critical. The Scale checkout page describes the Growth plan

The page where money changes hands misdescribes what is being bought.

| Plan | What the Polar checkout promises | What the product delivers |
|---|---|---|
| Starter $10 | 1,000 messages, **5** voice minutes, 2 seats, 50 sources | 1,000 messages, **60** voice minutes, 2 seats, 50 sources |
| Growth $20 | 5,000 messages, **20** voice minutes, 5 seats, 150 sources | 5,000 messages, **180** voice minutes, 5 seats, 150 sources |
| **Scale $60** | **5,000 messages, 20 voice minutes, 5 seats, 150 sources** | **20,000 messages, 480 voice minutes, 15 seats, 400 sources** |

Two separate defects wearing one coat:

1. **Every plan's voice figure is the pre-v0.13.0 number.** The ladder moved to
   5/60/180/480 in the code and on the landing page; the payment provider was never
   told. Under-promising, so nobody is overcharged — but the contractual text is wrong
   on all three products.

2. **Scale's description is a verbatim copy of Growth's**, down to "Everything in
   Starter, with room for a busy number." A customer paying $60 is shown the $20 plan's
   allowances: 5,000 messages instead of 20,000, 5 seats instead of 15. Beyond being
   wrong, it makes Scale look like dreadful value at the exact moment of purchase, which
   suppresses the conversion it is there to earn.

**Where it lives:** not in this repository. The strings are product metadata in the
Polar dashboard. Fixing them is a config change with no deploy. Verified by grep: no
file in the tree contains the phrase "minutes of voice replies".

**Not currently a mischarge risk.** `QONVO_BILLING_PRICE_MAP` holds exactly one product
per plan key, so `_price_id_for` cannot pick the wrong price today. That protection
disappears the moment an annual product is added, which is the risk already recorded in
`docs/ANNUAL-AND-HALF-YEARLY-BILLING.md`.

### [F] F2 — High. The in-app plan picker names no price

`GET /api/billing/plans` returns only `key`, `name` and `entitlements`. There is no
price field anywhere in the payload, so `/billing` physically cannot show one. An owner
reads allowances and deltas, presses **Choose**, and learns the price for the first time
on Polar's page.

The public landing page has named $10/$20/$60 since v0.13.0. The prices exist; they were
never plumbed into the product. This is the old L1/Z1/D1 finding, half closed: the site
names a price, the picker still does not.

### [F] F3 — Medium. `change-plan`, `cancel` and `resume` answer 200 when they fail

```
POST /api/billing/change-plan {"plan_key":"growth"}  -> 200 {"ok": false, "reason": "no_subscription"}
POST /api/billing/cancel      {}                     -> 200 {"ok": false, "reason": "no_subscription"}
POST /api/billing/resume      {}                     -> 200 {"ok": false, "reason": "no_subscription"}
```

A client that checks the status code believes the plan changed. Reported as **L3** on
11 September and still open.

### [F] F4 — Low. The trial banner contradicts the product

The dashboard banner reads *"14 days left in your free trial. Contact your Qonvo rep to
go paid."* while `/billing` offers working self-serve **Choose** buttons that issue real
checkout URLs. The banner is left over from when prices were not public.

---

## 2. Everything that was verified working

### [G] The v0.13.0 fixes all hold on production

| Check | Result |
|---|---|
| Tenant carries every entitlement key any plan defines | 7/7 |
| Tenant entitlements match the catalogue for its plan | exact |
| Trial is the floor on every allowance | holds |
| Cost of goods withheld from `totals`, from the daily series, and absent from the whole payload | withheld |
| A second WhatsApp number on a 1-number plan | `402 "Your plan includes 1 WhatsApp number..."` |
| 60,000-character knowledge entry | `422`, naming both the limit and the actual size |

The entitlement re-derivation (PR #68) is real on production: the number gate now
refuses, where before the release it enforced nothing for every tenant alive.

### [G] The C1 incident is not reproducible

Every shape that erased a live tenant's configuration on 11 September is now refused:

```
PUT /api/config {"persona": null}              -> 422
PUT /api/config {"totally_unknown_field": "x"} -> 422   (was a silent 200)
PUT /api/config {"primary_language": null}     -> 422   (was a 500)
PUT /api/config {"timezone": null}             -> 422   (was a 500)
```

A read-back confirmed the probes changed nothing.

### [G] Optimistic concurrency works (H4)

A real change at the current version returns 200 and bumps it; a second write at the
stale version returns **409** with *"Someone else changed these settings while you were
editing."* Last-write-wins is gone.

### [G] Signup, password rules and the verification gate

- A short password is blocked client-side with no request sent.
- A password equal to the email returns `400 weak_password`, and **the structured
  `detail` renders in the UI** — the M7 class of discarded-error bug is fixed.
- A password sharing a word with the business name is refused.
- Trial lands at exactly **14 days** with the catalogue's trial entitlements.
- An unverified owner may explore and prepare, and `POST /api/sessions` returns
  `403 email_unverified`. The gate is exactly where the security review argued for it.

### [G] The SSRF guard, the NUL byte, and the perimeter

Cloud metadata, loopback and `file://` are each refused `400` with a human message.
A NUL byte in JSON is `201`, not the 500 of the last round. An empty title is `422`.
No `server:` header naming uvicorn. Unauthenticated and forged tokens are `401`.

### [G] The UI, across every owner page

Eleven pages at 390 / 768 / 1440 px:

- **Zero horizontal overflow at 390px.** The H3 regression (`/knowledge` rendering
  922px wide at a 390px viewport) is fixed and has stayed fixed.
- **Zero console errors** on every page.
- **All ten sidebar routes return 200.**
- 147 interactive controls now live in `main`, against 106 counted in September.

### [G] The subscription lifecycle, driven on test01's live Polar subscription

| Step | Result |
|---|---|
| `change-plan` growth -> starter | `200 {"ok": true}`; entitlements became 1,000 messages / 60 voice minutes |
| `change-plan` starter -> growth | `200 {"ok": true}`; entitlements became 5,000 / 180 |
| Do the entitlements match the catalogue after each change? | **Exactly, both times** |
| `cancel` with a valid reason | `200 {"ok": true}`, `cancel_at_period_end: true`, period end unchanged |
| `resume` | `200 {"ok": true}`, `cancel_at_period_end: false` |
| Final state | growth, active, not cancelling - **restored** |

Cancelling sets the flag rather than ending the subscription, so a customer keeps what
they paid for until the period ends. That is the right behaviour and it is what happens.

Two contract details confirmed, both already reported as **L3** and both still open:
`cancel` with no body answers `422 {"loc": ["body"], "msg": "Field required"}` without
naming the field, and `resume` on a subscription that was never cancelled answers
`200 {"ok": false, "reason": "provider_unavailable"}` - a 200, and a reason that
describes the wrong thing.

A rejected `cancel` reason is handled well: `422` listing every permitted enum value.

### [G] Email verification, end to end on production

The welcome and confirmation emails both arrived (ZeptoMail, real), rendered correctly,
and the link worked. Confirmed server-side afterwards:

```
GET  /api/me        -> email_verified: true
POST /api/sessions  -> 201   (was 403 email_unverified before the click)
```

So the gate opens exactly when it should. The created session was deleted again:
`DELETE /api/sessions/{name} -> 204`, list back to empty - the **M6** fix works.

### [G] Webhook signature enforcement

```
no signature      -> 401 HMAC verification failed
wrong signature   -> 401 HMAC verification failed
forged signature  -> 401 HMAC verification failed
```

Nothing was processed in any case.

### [F] F5 - Low. An unknown session is distinguishable from a bad signature

A webhook for a session that does not exist answers `200 {"reason": "unknown_session"}`,
while a real session with a bad signature answers `401`. The difference is an oracle for
whether a session name exists. Session names carry a random suffix so enumeration is
impractical, and acknowledging the unknown one is deliberate (otherwise WAHA retries
forever) - but both could answer 200 and lose nothing.

### [F] F6 - Low. The API reports the raw daily cap, not the effective one

A freshly created session returns `daily_cap: 500, warmup_stage: 1`. The real ceiling is
50: `effective_daily_cap` takes `min(daily_cap, WARMUP_STAGE_CAPS[stage])` at send time.
The warm-up is genuinely enforced - but an operator reading the API or the Fleet console
sees 500 on a number that can actually send 50.

---

## 6. Documentation that has gone stale

Found while checking behaviour against what `CLAUDE.md` claims. None of these are
product faults; all of them would mislead the next person.

| Claim | Reality on production |
|---|---|
| WAHA image is `latest-2026.6.2`, and `latest-*` is a WEBJS build | Image is `latest-2026.7.2`, and `QONVO_WAHA_DEFAULT_ENGINE=NOWEB` is set deliberately |
| Staging admin password is in `~/qonvo-migration/staging-admin-password.txt` | That file does not exist |
| "A brand-new session starts at warm-up stage 1: 50 sends/day" | Correct, but the stored `daily_cap` is 500 and only the *effective* cap is 50, which is worth saying |

---

## 3. Retracted

Four findings from the first pass were my own test errors, not defects. Recorded because
the September audit made the same point: re-run a failure in isolation before believing
it.

| [R] | Why it was wrong |
|---|---|
| "SSRF guard broken — 422 not 400" (×3) | I omitted the required `title`, so the request died in validation before reaching the guard. With a title it returns the correct `400` and the human message. |
| "Optimistic concurrency broken" | I wrote the *same* value twice, so no UPDATE was emitted and the version never bumped. With a real change it behaves correctly. |
| "`/whatsapp` 404s" | I invented the path. The route is `/onboarding/connect`, and every sidebar link resolves. |

One probe did mutate production: `tone` was left as `AUDIT-PROBE-A` when a restore
command failed. It was restored from the snapshot taken before the run and verified
field by field — **zero fields differing**. Taking that snapshot first is the only
reason this is a footnote rather than a repeat of the September incident.

---

## 4. Not covered

| Area | Blocked on |
|---|---|
| Completing a card payment | hCaptcha and a Stripe iframe on Polar's page; also creates a real sandbox subscription |
| Injecting *valid* signed inbound webhooks | Reading the session HMAC secret from the production database was refused by the sandbox. The guard itself was tested; the pipeline behind it was not. |
| The live WhatsApp round trip, voice, debounce, takeover, skills | A phone number to message |
| Staff-role authorization from a staff login | A staff account |
| Admin console | Admin credentials not confirmed for this account |

## 5. Artefacts

A tenant **"Zephyr Clinic QA"** (`alihuzezzy+qonvoaudit@gmail.com`) was created on
production for the signup and checkout work. It is unverified, on trial, has no number
linked, and should be hard-deleted from Admin when the run finishes. Every other artefact
was removed: all knowledge sources created were deleted, and the source count returned to
its pre-audit value of 2.

Observed in passing: the dashboard returns **502 for a few seconds during every deploy**
while its container swaps. The Deploy workflow's own health check passed, so nothing
rolled back, but there is no zero-downtime swap on the dashboard.


---

## 9. Where it ended

Production went from **v0.12.0** (three weeks stale) to **v0.14.1** across this
session, in four releases, with every change through a pull request and CI.

### Verified on production after shipping

| Check | Result |
|---|---|
| URL knowledge ingestion, on the two URLs that failed before | both `ready` |
| `/readyz/deep` | `{"llm":"ok","whatsapp":"ok: 1 of 2 working"}` |
| `/readyz` (the deployment gate) | unchanged, `ok` throughout |
| Conversation state after unlinking the laptop | all five `bot_active` |

**`1 of 2 working` is worth acting on.** The fleet has two WhatsApp sessions and
one is not connected. That is the new probe doing exactly what it was built for
on its first day, and it is the kind of thing the old `/readyz` would have
reported as `ok`.

### [F] C9 - the probe reported itself

`/readyz/deep` shipped in v0.14.0 with `lower(session_status)` in its query,
which Postgres has no function for, so the check raised `ProgrammingError` on
every call. It was caught within minutes **by the probe itself**, `/readyz`
stayed green, and the deploy did not roll back -- the separation between the two
routes earning itself on day one. Fixed in v0.14.1.

### What still needs you

| | Why it is yours |
|---|---|
| **The three Polar product descriptions** | Product metadata in the Polar dashboard. No deploy. Scale still describes Growth. |
| **The real WhatsApp retest** | Deferred to last by agreement, now unblocked: the laptop is unlinked and production is the sole responder. |
| **Delete "Zephyr Clinic QA"** | A real tenant created on production for this audit. Hard-delete it from Admin. |
| **`QONVO_MINIO_ACCESS_KEY`** | Secret rotation on production. |
| **Backups are local-only** | An infrastructure decision, not a code change. |
| **One number is not connected** | `1 of 2` fleet sessions working. |

### Still untested

Skills that act (booking, order, lead capture), Google Calendar and Sheets,
takeover from the inbox UI, accepting a team invite as a staff user, file upload
ingestion, the admin console, completing a card payment, and session recovery.
The UI suite now exists to grow into these; today it covers billing, navigation
and phone width.
