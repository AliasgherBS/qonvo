# UI test runbook

Browser-driven tests over the flows that have actually broken. **Run on demand,
not in CI**, and this document is how.

## Why it is not wired into CI

It was, briefly, and it was wrong. The workflow ran on every pull request and
cost 46 seconds to decide it had nothing to run, which looks like a passing
check and is not one. Three things make the automatic version a bad trade here:

- **It needs a signed-in session.** Everything except the public landing page
  does. In CI that means owner credentials as repository secrets, on a public
  repository.
- **The target is a workstation.** Staging lives behind a tunnel on a laptop.
  A check that goes green when the laptop is off is worse than no check,
  because it will be believed.
- **A skipped job reads as a passing job.** A pull request that touches no UI
  module correctly runs nothing, and the only honest way to show that is a
  green tick that means nothing was looked at.

So the suite stays a tool you pick up, and `ui-tests.yml` is
`workflow_dispatch` only -- there if you want a run from the Actions tab, and
silent otherwise.

## Running it

```bash
cd e2e
npm ci
npx playwright install chromium     # once
```

### Against staging (the default)

```bash
npm test               # everything
npm run billing        # one module
npm run smoke          # the fast cross-cutting set
npm run report         # open the last HTML report
```

`QONVO_E2E_BASE` defaults to `https://dev.qonvo.org` and the credentials
default to the `seed_dev.py` owner, so this needs no setup on a seeded staging.

### Against production

Production needs **both** an explicit base and an explicit opt-in. The config
refuses otherwise, because pointing a suite that clicks buttons at production by
accident is a mistake you make once.

```bash
QONVO_E2E_BASE=https://qonvo.org \
QONVO_E2E_API=https://api.qonvo.org \
QONVO_E2E_ALLOW_PRODUCTION=1 \
QONVO_E2E_OWNER_EMAIL='you@example.com' \
QONVO_E2E_OWNER_PASSWORD='...' \
npm test
```

**Sign in as a tenant you are willing to have clicked.** Not a paying customer.
The suite is overwhelmingly read-only, but one probe posts to
`/api/billing/change-plan` to check that a refusal carries a failure status --
and on a tenant that *has* a subscription that same call succeeds. It refuses to
run in that case rather than quietly changing a real plan, but choose the
account deliberately anyway.

## What is covered

| Tag | Covers |
|---|---|
| `@smoke` | Navigation, and the one assertion per module worth running everywhere |
| `@billing` | Plan picker, prices, cost-of-goods leakage, failure status codes, the trial banner |
| `@knowledge` | The page renders, usage meters, the add-source control opens |
| `@inbox` | Filters, opening a conversation, a paused conversation offering a way back |
| `@settings` | Behavior, business settings fields, skills and their gating |
| `@analytics` | Both views render, and a chart never paints an empty grid |
| `@responsive` | Every page at 390px, plus the header controls staying on screen |

Each assertion is a bug that reached production: no price on the plan cards
(F2), `cost` in the analytics payload, a failed billing call answering 200
(L3/F3), the trial banner sending owners to a human (F4), a conversation stuck
in `paused_by_owner` with no way back, a chart painting an empty grid over a
zero series, and sideways scroll at 390px (H3), which shipped three times and
therefore gets its own phone project.

## What is NOT covered

Still needs a person, a phone, or an account that does not exist yet:

- Skills that act -- booking, order capture, lead capture
- Google Calendar and Sheets
- Accepting a team invitation and checking the staff role from a staff login
- File upload ingestion (PDF, DOCX, CSV)
- The admin console
- Completing a card payment (hCaptcha and a Stripe iframe)
- Session recovery and re-link

See `E2E-LIVE-TEST-PLAN.md` part 2 for the manual half.

## Reading a failure

**A red run often means the environment is stale, not that the code is wrong.**
Staging rebuilds its *dashboard* automatically and its API, worker and scheduler
containers not at all, so it can serve a new frontend against a backend from
three weeks ago. The first run of this suite found exactly that: `cost` was
still in staging's analytics payload, fixed in v0.13.0 and live on production.

```bash
./qonvo-staging.sh up        # rebuild the backend containers too
./qonvo-staging.sh migrate
curl -s https://dev-api.qonvo.org/readyz
```

Some tests skip rather than fail where the environment cannot support them: a
provider that states no price (staging runs `QONVO_BILLING_PROVIDER=manual`), a
tenant with no conversations, a tenant with a live subscription. A skip is the
suite declining to assert something that is not true of this environment, not a
test quietly giving up.

## Two things that will cost you an afternoon otherwise

- **Hydration.** The dashboard is server-rendered and the submit handler
  attaches on hydration. A fill-and-click that lands first produces no request
  at all, and the failure looks exactly like bad credentials. `signIn` waits;
  do not remove that wait.
- **The product tour is modal.** On a new tenant it covers the page and every
  click beneath it times out with "intercepts pointer events". `gotoPage`
  dismisses it.

## Last full run

**3 October 2026, against production, v0.14.1: 39 passed, 2 skipped.** The two
skips were the inbox tests, on a tenant with no conversations. The run confirmed
both billing fixes through the real interface: the plan cards name a price, and
a failed billing call no longer answers 200.
