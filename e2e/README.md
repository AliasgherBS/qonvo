# UI regression suite

Browser-driven tests over the flows that have actually broken. Its own package,
so the dashboard build never carries Playwright.

**Run on demand, not in CI.** The runbook -- how to run it, what it covers, what
it deliberately does not, and why a red run often means the environment is stale
rather than the code wrong -- is [`docs/UI-TEST-RUNBOOK.md`](../docs/UI-TEST-RUNBOOK.md).

```bash
npm ci && npx playwright install chromium
npm test            # everything, against staging
npm run billing     # one module
npm run report      # open the last HTML report
```

Production needs both an explicit base and `QONVO_E2E_ALLOW_PRODUCTION=1`; the
config refuses otherwise. See the runbook.
