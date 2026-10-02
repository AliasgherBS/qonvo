# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: billing.spec.ts >> @billing billing page >> a billing call that fails does not answer 200
- Location: tests/billing.spec.ts:56:7

# Error details

```
Error: a refusal must carry a failure status

expect(received).not.toBe(expected) // Object.is equality

Expected: not 200
```

# Test source

```ts
  1  | import { test, expect } from "@playwright/test";
  2  | import { gotoPage, failOnConsoleErrors } from "../lib/app";
  3  | 
  4  | /**
  5  |  * Billing is where money changes hands, so it carries the most regression
  6  |  * weight. Every assertion here is a bug that actually reached production.
  7  |  */
  8  | test.describe("@billing billing page", () => {
  9  |   test("@smoke every plan card names a price", async ({ page }) => {
  10 |     // Audit F2, 3 Oct 2026: /api/billing/plans carried no price field at all,
  11 |     // so the picker showed four allowances and no cost. The owner pressed
  12 |     // Choose and met the figure for the first time on the gateway's page.
  13 |     await gotoPage(page, "/billing");
  14 |     const cards = page.locator('[data-testid="plan-card"], main >> text=/^(Starter|Growth|Scale)$/');
  15 |     await expect(page.getByRole("button", { name: /Choose|Upgrade|Switch to this|Current plan/ }).first()).toBeVisible();
  16 | 
  17 |     const main = await page.locator("main").innerText();
  18 |     expect(main, "the plan picker must name a price, not only allowances").toMatch(/[$£€]\s?\d/);
  19 |   });
  20 | 
  21 |   test("the plan picker offers every paid plan", async ({ page }) => {
  22 |     await gotoPage(page, "/billing");
  23 |     const main = await page.locator("main").innerText();
  24 |     for (const plan of ["Starter", "Growth", "Scale"]) {
  25 |       expect(main, `${plan} must be offered`).toContain(plan);
  26 |     }
  27 |     expect(main, "the trial is not something you can buy").not.toMatch(/\bChoose\b[\s\S]{0,40}\bTrial\b/);
  28 |   });
  29 | 
  30 |   test("the trial banner does not send the owner to a human", async ({ page }) => {
  31 |     // Audit F4: the banner said "Contact your Qonvo rep to go paid" while
  32 |     // self-serve checkout worked three clicks away.
  33 |     await gotoPage(page, "/billing");
  34 |     const body = await page.locator("body").innerText();
  35 |     expect(body).not.toContain("Contact your Qonvo rep to go paid");
  36 |   });
  37 | 
  38 |   test("our cost of goods never reaches the tenant", async ({ page }) => {
  39 |     // Audit, 12 Sep: `cost` stayed in the analytics payload after the tile was
  40 |     // removed, so a customer with the network tab open could read our margin.
  41 |     const leaked: string[] = [];
  42 |     page.on("response", async (res) => {
  43 |       if (!res.url().includes("/api/analytics")) return;
  44 |       try {
  45 |         const body = await res.text();
  46 |         if (/"cost"\s*:/.test(body)) leaked.push(res.url());
  47 |       } catch {
  48 |         /* streamed */
  49 |       }
  50 |     });
  51 |     await gotoPage(page, "/analytics");
  52 |     await page.waitForTimeout(2000);
  53 |     expect(leaked, "analytics must not ship our cost of goods").toEqual([]);
  54 |   });
  55 | 
  56 |   test("a billing call that fails does not answer 200", async ({ page, request }) => {
  57 |     // Audit L3 (11 Sep) and F3 (3 Oct): change-plan, cancel and resume all
  58 |     // returned 200 {"ok": false}, so a client reading the status code believed
  59 |     // the plan had changed.
  60 |     const apiBase = (process.env.QONVO_E2E_API ?? "https://dev-api.qonvo.org").replace(/\/$/, "");
  61 |     const login = await request.post(`${apiBase}/api/auth/login`, {
  62 |       data: {
  63 |         email: process.env.QONVO_E2E_OWNER_EMAIL ?? "owner@dev.dev",
  64 |         password: process.env.QONVO_E2E_OWNER_PASSWORD ?? "dev-password-123",
  65 |       },
  66 |     });
  67 |     test.skip(!login.ok(), "no API login on this environment");
  68 |     const token = (await login.json()).access_token;
  69 | 
  70 |     const res = await request.post(`${apiBase}/api/billing/change-plan`, {
  71 |       headers: { Authorization: `Bearer ${token}` },
  72 |       data: { plan_key: "growth" },
  73 |       failOnStatusCode: false,
  74 |     });
  75 |     const body = await res.json().catch(() => ({}));
  76 |     if (body?.ok === false) {
> 77 |       expect(res.status(), "a refusal must carry a failure status").not.toBe(200);
     |                                                                         ^ Error: a refusal must carry a failure status
  78 |     }
  79 |   });
  80 | 
  81 |   test("the billing page renders without console errors", async ({ page }) => {
  82 |     const errors: string[] = [];
  83 |     failOnConsoleErrors(page, errors);
  84 |     await gotoPage(page, "/billing");
  85 |     await page.waitForTimeout(1500);
  86 |     expect(errors).toEqual([]);
  87 |   });
  88 | });
  89 | 
```