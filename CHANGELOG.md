# Changelog

All notable changes to Qonvo. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Branch flow: work lands on a feature branch, merges to `dev`, and is released to `main`
with an annotated `vX.Y.Z` tag. `Unreleased` below is what sits on `dev` awaiting a
release. See [CONTRIBUTING.md](CONTRIBUTING.md).

## [Unreleased]

## [0.14.1] - 2026-10-03

### Fixed

- **`/readyz/deep`'s own query was invalid SQL.** Shipped in 0.14.0 and reported by the
  probe itself within minutes of the deploy, which is the best outcome a readiness check
  can have and still a bug. `whatsapp_sessions.status` is a Postgres enum, and there is
  no `lower(session_status)`, so the case-insensitive comparison raised on every call and
  the check could never report anything but failure. `/readyz` was unaffected and the
  deploy did not roll back -- the separation between the two routes doing its job on its
  first day. The probe also said only "ProgrammingError", which tells an operator that
  something is wrong and nothing about what; it now carries the message.


## [0.14.0] - 2026-10-03

### Added

- **The plan picker names a price.** `GET /api/billing/plans` returned `key`, `name`
  and `entitlements` and nothing else, so `/billing` physically could not show a cost.
  An owner read four allowances, pressed Choose, and met the figure for the first time
  on a checkout page they had already committed to. The price is read **from the payment
  provider**, not added to `plans.py` -- that file says in its own docstring that prices
  deliberately do not live there, and the 3 October audit proved why: the Polar products
  still promise 20 voice minutes on a plan that grants 180, and the $60 Scale product
  carries Growth's description verbatim. A third copy here would have recreated the same
  bug facing the other way. A plan the provider cannot price renders without a figure
  rather than as free, and a provider outage leaves the page renderable.

- **`/readyz/deep`, a readiness probe that can tell healthy from dead.** On 2026-09-09 a
  firewall rule blocked all outbound TCP: WAHA could not reach WhatsApp, the LLM was
  unreachable, the bot was silent -- and `/readyz` reported everything ok throughout,
  because `waha: ok` only ever meant the API could reach the WAHA *container*. The new
  route adds the two things whose absence means no reply can be produced: the LLM
  endpoint is reachable, and some number is actually `WORKING`. Cached for 30 seconds
  with a 5 second timeout, and deliberately a connection check rather than a completion,
  because a readiness probe that spends money every thirty seconds is one nobody can
  leave running. It is a separate route because the deploy workflow greps `/readyz` for
  `"status":"ok"` and rolls back when it does not find it, so a tenant mid-rescan must
  not be able to fail a release.

- **A browser-driven UI regression suite** (`e2e/`), the first in this repository. CI ran
  typecheck, lint, a brand gate and a build, which proves the app compiles and never that
  a button works. It runs **per module rather than on every push**: a pull request that
  touches billing runs the billing specs and nothing else, and `workflow_dispatch` runs
  any module on demand. Every assertion is a bug that actually reached production.

### Fixed

- **Adding a website failed for almost every website.** `fetch_url_text` returned
  `httpx.DecodingError: Error -3 while decompressing data: incorrect header check` for
  every URL tried. `aiter_bytes()` yields bytes httpx has **already** decompressed, and
  the response rebuilt around them carried the original headers, still announcing
  `content-encoding: gzip`, so httpx decompressed the decompressed body. Compression is
  the default on essentially every host, so one of the three ways a tenant teaches their
  rep anything -- and the one on the onboarding checklist -- was broken for essentially
  every site. It failed quietly, too: the row sat at `error` with no reason an owner
  could act on.

- **A failed billing call no longer answers 200.** `change-plan`, `cancel` and `resume`
  all returned `200 {"ok": false}`, so a client checking the status code believed the
  plan had changed. Reported as L3 on 11 September. The body keeps its shape; only the
  status moves, to **409** when there is no subscription to act on and **502** when the
  provider is unreachable.

- **The trial banner stops sending owners to a human.** It read "Contact your Qonvo rep
  to go paid" while `/billing` offered working self-serve checkout three clicks away.

### Changed

- **Database pools are sized explicitly, per process.** Both engines used SQLAlchemy's
  defaults, which across api, worker and scheduler is 90 possible connections against
  `max_connections=100` -- and one extra worker replica takes it past the limit,
  surfacing as a burst of `TooManyConnections` rather than a graceful slowdown. The
  BYPASSRLS engine is kept deliberately small, since it serves a handful of trusted
  cross-tenant lookups and must never be why ordinary requests cannot get a connection.

- **The worker's concurrency ceiling has a name.** arq defaults `max_jobs` to 10 and
  `WorkerSettings` never set it, so grepping the codebase for it returned nothing and the
  reasonable conclusion was that no limit existed: the throughput ceiling of this product
  was a number in a dependency's source. It is still 10, so nothing moves; the point is
  that it can now be found and tuned.


## [0.13.0] - 2026-10-03

### Added

- **Voice and message shape in analytics.** `GET /api/analytics/summary` now reports
  inbound and outbound voice (count, total seconds, average seconds) and
  `message_shape` (count and average length per direction per type), plus
  `voice_seconds_in` / `voice_seconds_out` on every point of the daily series. An owner
  can finally answer "how long is a typical voice note" and "how long is a typical
  reply", which is the shape of the thing they are selling. Inbound audio duration gets
  its own column, because `voice_seconds` counts generated audio only and reusing it
  would report the rep's own speech back as the customer's.

- **Messages and voice as two views of one chart.** The two ask the same question of
  numbers that cannot share an axis, so the view swaps the series and the chart reads
  different accessors. Columns are buttons, so the figures are reachable by keyboard and
  on touch, and the whole column is the target -- a zero day has no bar to aim at and
  "nothing happened here" is worth being able to check.

- **Three priced tiers on the landing page.** $10 Starter, $20 Growth, $60 Scale, with
  Growth marked as where most businesses start. Every allowance is stated twice: as the
  thing an owner is buying, and as the number the meter counts. Conversions are
  deliberately conservative (a conversation taken as ten messages, both directions
  counted).

- **A language sampler on the landing page.** Pick a language, hear the same booking
  exchange spoken in it -- five clips of real product output. Replaces a voice sample
  that only ever demonstrated English sitting next to a claim about every language. The
  transcripts are the strings that were sent to the synthesiser, not translations made
  afterwards.

- **Contact as its own landing section, and in the header.** It existed only as a
  footnote under the pricing cards, which read as "how to ask about pricing" rather than
  "how to reach us". Placed after the FAQ, where somebody with an unanswered question is
  actually standing.

### Changed

- **Voice allowances meter generated audio only, and are much larger.** The allowance
  used to bound transcription plus synthesis, which spent the owner's allowance on the
  cheap half -- transcribing a minute costs $0.003, speaking one costs $0.0135 to
  $0.027, so a customer sending voice notes could exhaust an allowance a business bought
  for its replies. Transcription is now unlimited. With the meaning fixed the numbers
  were far too small, so they move from 5/20/100 to **5 / 60 / 180 / 480** generated
  minutes, re-costed against `docs/UNIT-ECONOMICS.md`. Trial's upload cap drops 50 MB to
  20 MB.

- **Pricing cards say "Sign up".** "Start free trial" under a card headed $20 a month
  reads as a different offer to the one priced directly above it.

- **Staging rebuilds itself.** `qonvo-staging-sync.timer` checks every minute whether
  the dashboard sources changed and rebuilds if they did; a source edit was live on
  `dev.qonvo.org` three minutes and sixteen seconds later. A failed build keeps the
  previous one serving. Building and serving are now separate scripts, which is the
  proper fix for a `--build` flag that ended by exec'ing the server and so could start a
  second one fighting for port 3012 -- the symptom being a change that would not appear
  no matter how many times you rebuilt.

### Fixed

- **A catalogue change reached nobody.** Entitlements are copied onto the tenant when a
  plan is applied, not read live from `plans.py`, so editing the catalogue changed what
  new tenants get and nothing at all for anyone who already existed. Everything you
  would check looked right, because `/api/billing/plans` and the pricing page both read
  the catalogue directly; only the tenant's own record was stale. **Every tenant in both
  environments was missing `whatsapp_numbers`**, and the number limit shipped in 0.12.0
  skips the check when the key is absent -- so that limit enforced nothing for every
  tenant that existed before it shipped, which was all of them. Starter tenants were
  also still on 5 voice minutes against a catalogue saying 60. Entitlements are now
  re-derived from the plan the tenant is actually on. Two tests guard the class rather
  than the instance: every plan must carry every entitlement key any plan defines, and
  the trial must be the floor on every allowance.

- **Our cost of goods was still being sent to tenants.** Teardown Y3 removed the "AI
  cost" tile but deliberately left `cost` in the response. That was half a fix -- the
  figure was still in `totals` and on every day of the series, so a customer with the
  network tab open could read our margin on their own account. Not showing something is
  not the same as not sending it. It is withheld where it is produced now; it remains
  measured, priced, and readable through `/admin/usage`.

- **The billing page said voice meters both directions.** It has not for a release. An
  owner who believes a chatty customer can burn their allowance turns voice off for the
  wrong reason. The copy now says so and says the generous half out loud. Nothing pinned
  that behaviour before; there is a test now, asserting the split at both ends.

- **The billing highlight pointed at team seats for every tenant alive.** An owner
  occupies a seat by existing, so a two-seat plan started at 50% on day one and nothing
  else cleared the 20% bar on a new tenant. Seats are now measured against the ones the
  owner can choose to fill.

- **The analytics hover card was drawn and then clipped.** `overflow-x-auto` makes the
  plot a scroll container, and a scroll container clips on both axes.

- **A series that is all zeroes drew an empty grid with a full axis.** A tenant with
  plenty of messages and no voice got a chart that painted nothing while the page
  insisted it was fine. Each view carries its own empty state. The axis also stopped
  printing "1" twice when the tallest bar is 1.

### Documentation

- **What a tenant actually costs, per plan** (`docs/UNIT-ECONOMICS.md`), and the voice
  economics of metering generation only.

- **A plan for annual and half-yearly pricing** (`docs/ANNUAL-AND-HALF-YEARLY-BILLING.md`),
  deferred rather than built. It records the finding that makes it worth writing down
  first: **adding an annual product to `QONVO_BILLING_PRICE_MAP` today would be a live
  mischarge risk**, because `_price_id_for` returns the first price mapping to a plan key
  and the map is a plain dict from the environment -- so a customer clicking "$20 a
  month" could be sent to a $204-a-year checkout, silently.

## [0.12.0] - 2026-09-11

### Fixed

- **A single `PUT /api/config` could erase a tenant's entire AI configuration and
  return 200.** `{"persona": null}` reached `setattr(row, "persona", None)`,
  because `exclude_unset` means an explicit null is *sent* rather than absent. A
  live tenant lost its business name, persona, tone, payment details and 1,821
  characters of grounding rules that way, while the rep was answering customers.
  Two of the columns are NOT NULL, so the same request crashed with a 500 there
  instead — the same bug wearing a different face. Null is now refused on
  content, and still clears the three fields where absence is a state someone
  deliberately chooses (`billing_email`, `llm_provider`, `llm_model`). Send `""`
  to blank a text field. Unknown field names are a 422 rather than a 200 with an
  unchanged body, so a typo can no longer report success.

- **The NUL byte, found twice, fixed once.** `0x00` is legal in a Python string
  and illegal in a Postgres text column, so it survives every layer until the
  INSERT. It first appeared as a worker crash that hung a real 391 KB PDF on
  "Processing"; that fix landed on the file path, and the byte then arrived
  through the JSON API instead, as a 500. Sanitising now happens at the request
  model, which is the boundary every entry point crosses, reusing the function
  the file path already uses so the two cannot drift. Arabic, CJK and emoji are
  untouched.

- **Three pages scrolled sideways on a phone, taking the header controls with
  them.** `/knowledge` rendered 922px wide at a 390px viewport with the rep
  switch, the bell and the avatar off-screen. The tables were already wrapped in
  `overflow-x: auto`; those wrappers were correct and completely inert, because a
  scroll container can only scroll once an ancestor has bounded it. One `min-w-0`
  on the shell's flex column fixes Knowledge, Billing and Analytics, and
  inoculates every future table.

- **Small talk is no longer logged as a knowledge gap.** "Hello how are you
  doing?" led the owner's report under a tile telling them to write a knowledge
  article about it. Genuine gaps — opening hours, cancellation policy, a refund
  complaint — were always logged correctly; only small talk was getting through.

- **The "your number is back online" email is gone.** It is the one alert whose
  own body says nothing needs doing, and the owner already has the news by the
  more direct route of their number working again. It remains a dashboard
  notification and a WhatsApp ping. The outage alert still emails, and still
  fires once per outage rather than once per poll.

- **A knowledge source can no longer be created with an empty title**, which
  returned 201 and rendered a blank row nobody could identify.

- **`seed_dev.py` printed a password it had not set.** It created accounts only
  when missing, then reported `OWNER_PASSWORD` unconditionally, so on an existing
  user it advertised a credential that did not work — and the runbook documented
  re-running it as the recovery route for a locked-out account. It now resets both
  accounts, prints the admin pair too, and leaves any enrolled second factor alone.

### Added

- **WhatsApp numbers are bounded by plan**: one on Trial, Starter and Growth, two
  on Scale. Creation was unbounded, and each number is a WAHA session at roughly
  22 MB, which is the RAM ceiling of the box.

- **A session can finally be removed** — but only when nothing hangs off it.
  `conversations` cascade from `whatsapp_sessions` and `messages` from
  `conversations`, so deleting a used session would take the tenant's history with
  it and return 204 as though nothing happened. An unused row deletes; one with
  history returns 409 naming the conversation count and pointing at Log out.

### Changed

- **The interactive API docs are off in production** and work properly
  everywhere else. `/docs` returned 200 and rendered an empty page, because
  Swagger loads its assets from a CDN and the blanket `default-src 'none'` blocked
  them — so production advertised an explorer that did not work. `/openapi.json`
  goes too, since it is the part that enumerates the surface.

## [0.11.2] - 2026-09-10

### Added

- **Production deploys itself from a release tag.** `dev` already merged itself
  when CI went green; the other half was missing, so going live still meant a
  person on an SSH session. A tag now triggers a deploy, and rolling back is
  re-running the workflow with an older tag rather than reverting commits and
  hoping the rebuild matches. The credential is a **forced-command SSH key**:
  whatever the workflow sends arrives as an argument to a script that accepts
  nothing but a `vX.Y.Z` tag that exists on origin, so a leaked CI secret is
  not server access. Verified against the live box, which refuses a shell,
  refuses `rm -rf`, refuses a branch name and refuses a tag that does not
  exist. The deploy builds before switching, rolls back if `/readyz` does not
  recover, and checks the **public** URLs rather than only the containers.

- **[Measured capacity, and the nine things that cap it](docs/CAPACITY-AND-SCALING.md).**
  The load test the cost doc admitted had never been run. ~50-70 tenants as
  shipped, ~150-200 tuned, on 4 vCPU and 8 GB. CPU is not the limit: at three
  times the current ceiling the box uses 0.85 of four cores, because the
  workers idle-wait on HTTP. The ceiling is a concurrency default nobody set,
  living in a dependency's source rather than in this codebase.

### Fixed

- **Staging was publicly indexable.** `dev.qonvo.org` went live serving the
  same marketing copy as production, with `robots.txt` saying `Allow: /` and no
  `X-Robots-Tag`, so it would have been indexed as duplicate content against
  the real site. The runbook pointed at the Caddyfile, but staging reaches the
  internet through the Cloudflare Tunnel, which applies no headers at all, so
  the app has to say it itself. Both signals are sent, because they fail
  differently: `robots.txt` asks, `X-Robots-Tag` tells a crawler that arrived
  without reading it.

- **CI could not validate the compose file.** The `dashboard` service began
  reading `dashboard/.env.local`, which is gitignored, so a fresh checkout had
  nothing to read and `docker compose config` failed on every branch. Fixed the
  way `.env` was already handled one line above: copy the tracked template into
  place.

## [0.11.1] - 2026-09-10

### Fixed

- **The containerised dashboard was never actually configurable.** The compose
  `dashboard` service passed `NEXT_PUBLIC_API_URL` as a runtime environment
  variable, which does nothing: `next build` inlines `NEXT_PUBLIC_*` into the
  client bundle, so the value was already fixed by the time the container
  started. With no build args declared, the image would have sent every browser
  API call to `http://localhost:8000`, published `http://localhost:3002` as the
  canonical origin in the sitemap and OG tags, and emitted a CSP whose
  `connect-src` omitted the API — blocking the calls regardless. With no
  `env_file` it also had no `AUTH_SECRET`, so Auth.js could not sign a session
  cookie, and no `AUTH_URL`, reproducing a `redirect_uri_mismatch` this project
  has already paid for once. None of it had ever surfaced because dev and
  tunnel-era production both ran the dashboard as a host node process. The
  three baked values are build args now, and the build **fails** rather than
  defaulting when they are missing.

- **Caddy still served the dashboard from `app.<DOMAIN>`.** Production is on the
  apex — which is what `NEXT_PUBLIC_SITE_URL`, `AUTH_URL` and the Google console
  redirect URI already said. Caddy was the last place disagreeing, and it is the
  one that decides which certificate to request, so on a VPS it would have asked
  for a certificate for a hostname with no DNS record and taken the whole stack
  down with it. Adds the `www` → apex redirect.

- **A rewrite destination that looked like a runtime read was baked at build
  time.** `next.config.ts` asserted that `INTERNAL_API_URL` "is read at server
  start, so it works in standalone". Next serialises `rewrites()` into
  `routes-manifest.json` during the build. Demonstrated on a running container
  that held `INTERNAL_API_URL=http://api:8000` in its environment and could
  fetch `http://api:8000/healthz` from inside itself, while `/backend/healthz`
  returned 500 because the manifest said `localhost:8000`. Harmless until now
  only because the host process runs where `localhost:8000` really is the API.

### Added

- **`dashboard/.env.local.example`**, which the docs already claimed was tracked
  but which did not exist — a fresh clone had no template for the nine variables
  the dashboard needs, and the two that are read at build time were
  indistinguishable from the seven that are not.

## [0.11.0] - 2026-09-09

### Added

- **A readable audit log in the ops console.** Every state-changing admin action was
  recorded and none of it could be read without psql. There is now a reader with
  tenant, actor and action filters, paged on the server and ordered with `id` as a
  tiebreak so paging cannot repeat or skip a row. The three actor shapes that had
  accumulated are reconciled, and an impersonated action shows who was really behind
  it rather than reading as the customer's own.

- **A second factor on the `qonvo_admin` account**, enrolled by scanning a QR rather
  than typing a secret. The encoder is checked by a gate that rasterises the QR and
  decodes it with a different library, because a QR that renders is not a QR that
  scans, and a wrong one fails at the moment somebody is locked out.

- **"Improve with AI" on custom instructions.** Rewrites what an owner wrote into
  something the prompt builder can honour, and says what it changed.

- **Email verification at signup**, and an owner can see and revoke their own
  sessions.

- **Plan, trial and impersonation controls in the console**, so support does not need
  psql for the three things it needed it for most.

### Changed

- **The rep no longer promises what the business never offered.** The system prompt
  instructed the model to reassure and offer a callback, so it was manufacturing
  commitments the owner had never made — a customer was told "our team will call you
  back within the hour" when nobody was going to call. The prompt guard-rails; the
  call to action belongs to the owner. Verified live: asked for a branch that does not
  exist and a callback, the rep now says it does not have that detail rather than
  inventing either.

- **An owner's instructions can no longer contradict the tools the rep has.** A
  connected integration wins over prose that argues with it, and an instruction that
  contradicts a live capability is surfaced to the owner instead of being silently
  obeyed or silently dropped.

- **Skills are described in the prompt, not only offered as tools.** Six were offered
  on every turn and chosen on none. The one the model did use, `human_handoff`, was
  the only one named in the prompt text.

- **One date format across the product** (`4 Sept 2026`), one timezone per tenant, and
  the inbox names the customer.

### Fixed

- **Marking a customer paid now grants what they paid for.** The console wrote
  `tenants.plan` while entitlements kept whatever the previous plan allowed, so an
  operator who took a bank transfer left the customer capped at the trial's 300
  messages while the console reported a paid plan. Plan changes go through
  `apply_plan`, which derives entitlements from the catalogue, and the old field is
  kept only so it can be refused with an explanation.

- **A refreshed knowledge source stops billing for text it no longer holds.**
  Re-ingesting tombstoned the previous chunks instead of deleting them. Every reader
  filtered those out except the character quota, which counted them all — so
  refreshing a page charged the business again, permanently, and the owner's own page
  and the quota disagreed by exactly the overcharge. Nothing purged them either.

- **A dead ingestion job can no longer look alive.** A failure at COMMIT happens as
  the transaction context exits, after any handler inside it, so a source could log
  "ingested" and then fail with nothing marked. The failure is now caught outside the
  session, recorded on a fresh connection, and shown to the owner with a readable
  reason instead of a bare "error".

- **A number that stops answering tells its owner.** One sat at FAILED for about
  twenty hours, reported accurately on Fleet Health and nowhere else: the only alert
  hung off the recovery budget, and that session had no credentials to restart into,
  so nothing retried, nothing exhausted, and nobody was told. Owners are now alerted
  three minutes into an outage, once per episode, and the give-up notice half an hour
  later says what changed rather than repeating the first.

- **Voice is metered from what the provider reports**, not from the size of the file.
  A byte-rate assumption of 2,000 B/s applied to a 48,000 B/s WAV over-reported a
  ten-second note by twenty-four times.

- **Prompt-cache hit rate on every message.** The tool array was built from a `set`,
  so several thousand bytes at the front of every request reshuffled between calls
  and the cached prefix never matched.

- **One usage number, one meaning.** The same 89 stored seconds read as "2 min of 5"
  on the owner's page and as 89 on the admin endpoint, and neither said which unit or
  whose usage it was.

- **Fleet Logout no longer sits next to Restart as an equal.** It destroys the
  WhatsApp pairing and needs a physical phone to undo, so it now asks for the business
  name in full and points at Restart as the thing you probably meant.

### Security

- **A 422 no longer hands back what it rejected.** pydantic sets `input` to the whole
  submitted body for a `missing` error, so any route with a required field returned
  every other field: `POST /api/auth/signup` came back with a new customer's plaintext
  password, `reset-password` with the reset token, the admin config route with a
  tenant's bank details, and the inbox reply route with the message a business was
  sending a customer. Fixed app-wide rather than per router, because a curated list of
  "endpoints that carry secrets" missed four and then a fifth.

- **Staff seats could cancel the subscription, change the plan, turn the rep off and
  rewrite the payment details** the rep reads out to customers. `require_owner`
  existed and was used in two modules out of twenty-one. Asserted now as a property of
  the route table rather than per endpoint, so a new route is owner-only until it is
  deliberately listed.

- **Ten ordinary logins no longer lock out an office.** The per-address counter
  counted successes and was never cleared, so ten correct logins from one connection
  refused the eleventh for fifteen minutes — which in this market means a shared
  office line, or a stranger behind the same CGNAT address.

- **Every per-address rate limit was bypassable with one header, on production.**
  `X-Forwarded-For` is caller-supplied and Cloudflare only adds to it, so rotating it
  meant no counter ever filled. That covered the five-signups-per-hour cap, which is
  the only thing between a script and unlimited tenant rows. Now keyed on
  `CF-Connecting-IP`, confirmed against production rather than assumed.

- **A stranger can no longer lock you out of your own business.** Eleven deliberate
  failures on a known address refused the owner's correct password for fifteen
  minutes, from anywhere, repeatably. Failures are now counted per (account, address)
  with a much larger backstop for the distributed case.

- **Tokens can be revoked, so signing out signs you out.** A session had no `jti`, so
  logging out cleared the browser's copy and left the credential valid for the rest of
  its 24 hours.

- **A real password policy**, screened against known breaches, with the work factor
  pinned so it cannot silently weaken.

- **The server refuses to fetch a URL that points inside our own network**, on every
  resolved address and again on each redirect hop.

- **Google Sheets picking works**, and a blocked frame now fails with a sentence
  naming the origin instead of hanging: `docs.google.com` was never in `frame-src`.


## [0.10.2] - 2026-09-08

### Security

- **`script-src` no longer allows `'unsafe-inline'`.** A per-request nonce
  replaces it, so the policy allows our own inline scripts specifically rather
  than inline scripts generally: a browser runs a script only if it carries this
  response's value, and an injected one cannot know it. That moved the policy
  from `next.config.ts`, where `headers()` is evaluated once at build time, into
  middleware. Every redirect path is covered too, since a response that skipped
  the wrapper answered with no policy at all, and `/login` is the response an
  unauthenticated visitor sees most often.


## [0.10.1] - 2026-09-08

### Fixed

- **Cancelling a plan returned 422.** `apiFetch` already stringifies a plain
  object and sets `Content-Type`, and only for a plain object, so passing an
  already-stringified body skipped both and the API received JSON with no content
  type. The same mistake was in the rep on/off toggle, which had never been
  exercised. `apiFetch` now warns in development when handed a stringified body,
  since the failure surfaces two layers from its cause.

- **A customer with one payment could not get an invoice.** The link was only
  offered when the provider reported the document as generated, and that is false
  on every fresh order: Polar issues an invoice *number* at purchase and renders
  the PDF only when asked. Invoices are now generated on demand, and the link is
  fetched per click because the provider's URL is signed and short-lived.

- Cloudflare injects its Web Analytics beacon at the edge, so the CSP blocked a
  script this codebase does not add and cannot remove, producing a violation on
  every page load and a follow-on TypeError from the half-loaded script.

### Changed

- **Plan management no longer leaves the app.** Changing plan happens in place and
  is prorated by the provider; cancel-and-resubscribe would have restarted the
  billing period and charged full price on the day somebody downgraded. What
  remains in the provider's portal is card details and only that, since hosting a
  card form means handling card data. The button says "Update card" rather than
  "Manage plan", which had been sending people away to do things the billing page
  could already do.

- The Terms name **"Aliasghar Ezzy, trading as Qonvo"** rather than "Qonvo".
  Qonvo is a product name; with no company registered the seller is a natural
  person, and a Terms page naming an entity that does not exist against a payment
  provider's KYC naming an individual is the mismatch that fails a
  merchant-of-record review.


## [0.10.0] - 2026-09-08

The release that made Qonvo sellable: a public domain, real email, a payment
gateway that has taken a real payment, and limits on everything that costs money.

### Added

- **Live on `qonvo.org`**, served from a Cloudflare Tunnel so no public IP or port
  forwarding is needed. `qonvo-up.sh` now curls both public URLs at the end rather
  than reporting that a tunnel started: a tunnel that connects but routes nowhere
  looks identical to a healthy one from the machine it runs on. Runbook, including
  rollback: [docs/GOING-LIVE-ON-A-DOMAIN.md](docs/GOING-LIVE-ON-A-DOMAIN.md).

- **Email on the domain**, about $1/month: Zoho Mail for the mailbox, ZeptoMail for
  what the app sends, from `send.qonvo.org` so a marketing mistake can never stop a
  password reset arriving. `scripts/dns-email.sh` writes the records idempotently and
  its `check` subcommand detects the three ways this silently breaks. See
  [docs/EMAIL-SETUP.md](docs/EMAIL-SETUP.md).

- **Polar as merchant of record.** A full adapter behind the existing provider seam,
  covering checkout, both of Polar's webhook signing schemes (it changed them on
  2026-09-08), payment history, an authenticated portal link, and in-app cancel and
  resume at end of period. Verified end to end against a real sandbox payment.

- **Voice allowance**, 5/20/100 minutes by plan. Voice was ungated and is 54-74% of
  per-tenant AI cost, so an unlimited-voice tenant on the largest plan cost about $54
  a month against $30 of revenue. Running out **degrades to text** rather than going
  silent, and the customer is told once per period.

- **Input caps**, at the API boundary and again at ingestion, because a URL source has
  no size until it has been fetched. Prompt fields are small and fixed; knowledge is
  generous and per-plan, since retrieval means a large corpus never makes a reply more
  expensive.

- **Activation.** A new tenant's rep now starts **off**. Previously it began answering
  real customers from an empty knowledge base the moment the QR code was scanned.
  While off, messages still arrive and are visible; the owner answers by hand.

- **Usage visibility.** Meters for messages, voice, seats and knowledge on the owner's
  billing page, and a fleet view sorted worst-first in the admin console, both from
  one computation so the two can never disagree.

- **Onboarding**: a five-step checklist that ends in switching the rep on, so
  onboarding and going live are one journey, plus a four-step tour over the real UI.

- **Rate limiting** on login, signup and password reset. Two keys per attempt, and the
  account counter records failures only, so an attacker cannot lock a victim out of
  their own account by failing on their behalf.

- **Security headers on both hosts**, set in application middleware rather than the
  proxy so they survive the move from Cloudflare Tunnel to Caddy.

- [docs/DEPLOYMENT-AND-COSTS.md](docs/DEPLOYMENT-AND-COSTS.md): measured resource
  profile, per-tenant storage model, VPS provider comparison at September 2026 rates,
  and the self-hosted versus managed Postgres decision. AI costs are catalogued
  **provider-agnostically** — 18 language models, 11 TTS and 13 STT providers, each
  normalised to this deployment's measured cost per 1,000 replies — plus a section on
  what can actually be bought and paid for from Pakistan.

- [docs/SECURITY-AUDIT.md](docs/SECURITY-AUDIT.md): the findings, the fixes, and what
  is still open.

### Changed

- Transactional emails are on the **actual brand palette**. They had drifted to a
  near-miss set that nothing checked, because the brand gate only walks the dashboard
  tree. A new plan-confirmation email says what the provider's receipt cannot: not
  that a business paid $18, but that their allowance went from 300 messages to 5,000.

- The **engine picker is off the owner's Business page**. Choosing a model is not a
  decision a business owner is equipped to make, and every wrong answer costs quality
  or money with no signal. Still editable from the admin console for incident pinning.

- Trial terms live in one place and a test fails if the number is retyped anywhere
  else, across the Python/TypeScript boundary.

### Fixed

- **The upload route read whole files into memory.** `await file.read()` with no size
  check anywhere, so one large upload was an availability problem, not a cost one.

- **`knowledge_chars` measured the wrong table.** A tenant showed 2 sources and 0
  characters against 7,775 genuinely stored: `sources.content` is NULL for anything
  uploaded or fetched. The cap would not have bound at all on file-based knowledge.

- **A customer's first payment resolved to no tenant.** The tenant id was written into
  checkout metadata and never read back, and the event that creates the subscriptions
  row is the first one, so there was nothing to match on. They would have kept their
  old plan having paid for a new one, silently, with the provider seeing a 200.

- **An authentic webhook we do not act on answered 401.** Providers send far more
  event types than any integration uses, and a provider that keeps getting errors
  eventually disables the endpoint.

- **Ten live secrets were in git history.** `.env` was tracked once; a removed file
  stays in history. Four were also placeholder-shaped strings, which is worse: those
  are guessable with no repository access. All rotated by
  `scripts/rotate-secrets.sh`, including re-encrypting what the Fernet key protects.

- **A credential in the URL.** Polar appends a session token to its success URL, so it
  reached browser history, `Referer` and access logs. Stripped in middleware, with
  `/reset-password` and `/accept-invite` exempt because our own emails link there.

## [0.9.0] - 2026-09-05

The first tagged release. Everything before it was untagged work on `main`. This
marks the product as live-verified against a real WhatsApp number, with the
billing, staging, CI and test-harness work that closed the last gaps before it
could be sold.

### Added

- **Automated end-to-end smoke test** (`./scripts/e2e-smoke.sh`): 45 checks over
  infrastructure, auth, every owner read endpoint, the billing lifecycle, knowledge
  ingestion and the inbound pipeline, driven by signed synthetic webhooks so no phone
  is needed. Plus [docs/E2E-LIVE-TEST-PLAN.md](docs/E2E-LIVE-TEST-PLAN.md) for the
  manual half and a standing record of what has actually been exercised.

- **Billing subsystem**, provider-agnostic and shaped around a merchant of record,
  shipped with a manual (admin-recorded) adapter so it works before any gateway
  account exists. Plan catalogue in code with entitlements only, `subscriptions` and
  `billing_events` tables (migration `0008`), a pure `service_state` entitlement gate,
  seat limits on team invites, an idempotent `POST /webhooks/billing/{provider}` route,
  and `PUT /api/admin/tenants/{id}/subscription`. Prices deliberately live with the
  payment provider, never in this repository.
- **Staging environment** (`./qonvo-staging.sh`): a second compose project beside
  production with its own volumes, secrets and ports, and email forced to `log` so it
  can never reach a real customer.
- **New-number warm-up** is now actually applied: 50 sends/day for week one, 150 for
  week two, then normal, advanced by a daily scheduler job.
- `QONVO_WAHA_FULL_SYNC` (default off) — see Changed.
- Continuous integration: backend tests, lint, migrations and the dashboard build and
  brand gates run on every push and pull request.

### Changed

- **WAHA no longer backfills WhatsApp history** into its own store by default.
  Measured at roughly 1.3 KB per historical message and 4 KB per contact ever seen —
  one test number had cached 19,471 messages to serve a product that had used 41 of
  them. Nothing reads that history; conversation context comes from Postgres. Applies
  to newly created sessions.
- Backups no longer archive the WAHA message store, keep 7 days instead of 14, and
  write a single compressed archive per night.

### Fixed

- **A provider failure no longer discards the customer's message.** The whole turn
  ran in one transaction, so an LLM outage or exhausted quota rolled back the inbound
  message, the conversation, the handoff and the notification, while the "a customer
  needs a human" email had already been sent. The owner got an alert and an empty
  inbox, and Redis-keyed dedupe then dropped WhatsApp's redelivery, losing the message
  for good. The inbound message is now committed before the model is called.

- **`alembic upgrade head` failed on any fresh database.** Migration `0001` builds the
  schema from the current models, so `0007`'s unguarded `add_column` collided with
  columns that already existed, aborting the upgrade. Every new deploy would have
  failed at this step.
- **The daily send cap and warm-up ceiling were not enforced on bot replies** — the
  overwhelming majority of outbound traffic. Manual replies and booking reminders
  honoured them; the pipeline passed a default. `pacing` is now a required argument on
  the send gateway so it cannot silently default again.
- **AI cost was priced against the wrong model** for any tenant configured through the
  nested `providers` map, usually recording $0.00 because the wrong model name misses
  the pricing table. Pricing and provider construction now share one resolver.

### Security

- MinIO's host ports are bound to localhost instead of every interface.
- Application containers read their environment from `${QONVO_ENV_FILE}`, so a second
  stack cannot silently run on production's JWT, Fernet and WAHA secrets.

[Unreleased]: https://github.com/AliasgherBS/qonvo/commits/dev
[0.9.0]: https://github.com/AliasgherBS/qonvo/releases/tag/v0.9.0
[0.10.0]: https://github.com/AliasgherBS/qonvo/releases/tag/v0.10.0
[0.10.1]: https://github.com/AliasgherBS/qonvo/releases/tag/v0.10.1
[0.10.2]: https://github.com/AliasgherBS/qonvo/releases/tag/v0.10.2
[0.11.0]: https://github.com/AliasgherBS/qonvo/releases/tag/v0.11.0
[0.11.1]: https://github.com/AliasgherBS/qonvo/releases/tag/v0.11.1
[0.11.2]: https://github.com/AliasgherBS/qonvo/releases/tag/v0.11.2
[0.12.0]: https://github.com/AliasgherBS/qonvo/releases/tag/v0.12.0
[0.13.0]: https://github.com/AliasgherBS/qonvo/releases/tag/v0.13.0
[0.14.0]: https://github.com/AliasgherBS/qonvo/releases/tag/v0.14.0
[0.14.1]: https://github.com/AliasgherBS/qonvo/releases/tag/v0.14.1
