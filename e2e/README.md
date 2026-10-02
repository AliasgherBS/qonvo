# UI regression suite

Browser-driven tests over the flows that have actually broken. Its own package,
so the dashboard build never carries Playwright.

```bash
cd e2e && npm ci && npx playwright install chromium

npm run billing        # one module
npm run smoke          # the fast cross-cutting set
npm test               # everything
npm run report         # open the last HTML report
```

## It points at staging

`QONVO_E2E_BASE` defaults to `https://dev.qonvo.org`. These tests click real
buttons against a real stack, so production needs **both** an explicit base and
`QONVO_E2E_ALLOW_PRODUCTION=1`; the config refuses otherwise.

```bash
QONVO_E2E_BASE=https://qonvo.org \
QONVO_E2E_API=https://api.qonvo.org \
QONVO_E2E_ALLOW_PRODUCTION=1 \
QONVO_E2E_OWNER_EMAIL=... QONVO_E2E_OWNER_PASSWORD=... npm run billing
```

## Tags are the point

Every test carries a module tag, so a billing PR can run the billing suite and
nothing else. That is also how CI stays cheap: see
`.github/workflows/ui-tests.yml`, which runs a module only when that module's
files changed, and otherwise runs nothing at all.

| Tag | Covers |
|---|---|
| `@smoke` | Navigation, and the one assertion per module worth running everywhere |
| `@billing` | Plan picker, prices, entitlements, cost leakage, failure status codes |
| `@responsive` | Phone width on every page (the H3 regression) |

## Two things that will waste your afternoon otherwise

- **Hydration.** The dashboard is server-rendered and the submit handler
  attaches on hydration. A fill-and-click that lands first produces no request
  at all, and the failure looks exactly like bad credentials. `signIn` waits.
- **The product tour is modal.** For a new tenant it covers the page and every
  click beneath it times out with "intercepts pointer events". `gotoPage`
  dismisses it.

## A red run may mean the environment is stale, not the code

Staging rebuilds its **dashboard** automatically and its **API, worker and
scheduler containers not at all**. A new frontend can therefore run against a
backend from three weeks ago, and these tests will correctly fail against it.
The first run of this suite found exactly that: `cost` was still in staging's
analytics payload, fixed in v0.13.0 and live on production.

Before believing a failure, check what the environment is actually running:

```bash
./qonvo-staging.sh up        # rebuild the backend containers too
curl -s https://dev-api.qonvo.org/readyz
```
