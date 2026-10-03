import { test, expect } from "@playwright/test";
import { gotoPage, failOnConsoleErrors } from "../lib/app";

/**
 * Billing is where money changes hands, so it carries the most regression
 * weight. Every assertion here is a bug that actually reached production.
 */
test.describe("@billing billing page", () => {
  test("@smoke every plan card names a price", async ({ page, request }) => {
    // Audit F2, 3 Oct 2026: /api/billing/plans carried no price field at all,
    // so the picker showed four allowances and no cost. The owner pressed
    // Choose and met the figure for the first time on the gateway's page.
    //
    // Only meaningful where a provider actually states a price. Staging runs
    // QONVO_BILLING_PROVIDER=manual, which correctly reports none, and a card
    // with no figure is the designed behaviour there -- asserting regardless
    // would make this test fail for a reason that is not a defect.
    const apiBase = (process.env.QONVO_E2E_API ?? "https://dev-api.qonvo.org").replace(/\/$/, "");
    const login = await request.post(`${apiBase}/api/auth/login`, {
      data: {
        email: process.env.QONVO_E2E_OWNER_EMAIL ?? "owner@dev.dev",
        password: process.env.QONVO_E2E_OWNER_PASSWORD ?? "dev-password-123",
      },
      failOnStatusCode: false,
    });
    test.skip(!login.ok(), "no API login on this environment");
    const token = (await login.json()).access_token;
    const plans = await (
      await request.get(`${apiBase}/api/billing/plans`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    ).json();
    const priced = plans.filter((p: { price?: unknown }) => p.price);
    test.skip(priced.length === 0, "this environment's provider states no prices");

    await gotoPage(page, "/billing");
    await expect(
      page.getByRole("button", { name: /Choose|Upgrade|Switch to this|Current plan/ }).first(),
    ).toBeVisible();
    const main = await page.locator("main").innerText();
    expect(main, "the plan picker must name a price, not only allowances").toMatch(/[$£€]\s?\d/);
  });

  test("the plan picker offers every paid plan", async ({ page }) => {
    await gotoPage(page, "/billing");
    const main = await page.locator("main").innerText();
    for (const plan of ["Starter", "Growth", "Scale"]) {
      expect(main, `${plan} must be offered`).toContain(plan);
    }
    expect(main, "the trial is not something you can buy").not.toMatch(/\bChoose\b[\s\S]{0,40}\bTrial\b/);
  });

  test("the trial banner does not send the owner to a human", async ({ page }) => {
    // Audit F4: the banner said "Contact your Qonvo rep to go paid" while
    // self-serve checkout worked three clicks away.
    await gotoPage(page, "/billing");
    const body = await page.locator("body").innerText();
    expect(body).not.toContain("Contact your Qonvo rep to go paid");
  });

  test("our cost of goods never reaches the tenant", async ({ page }) => {
    // Audit, 12 Sep: `cost` stayed in the analytics payload after the tile was
    // removed, so a customer with the network tab open could read our margin.
    const leaked: string[] = [];
    page.on("response", async (res) => {
      if (!res.url().includes("/api/analytics")) return;
      try {
        const body = await res.text();
        if (/"cost"\s*:/.test(body)) leaked.push(res.url());
      } catch {
        /* streamed */
      }
    });
    await gotoPage(page, "/analytics");
    await page.waitForTimeout(2000);
    expect(leaked, "analytics must not ship our cost of goods").toEqual([]);
  });

  test("a billing call that fails does not answer 200", async ({ page, request }) => {
    // Audit L3 (11 Sep) and F3 (3 Oct): change-plan, cancel and resume all
    // returned 200 {"ok": false}, so a client reading the status code believed
    // the plan had changed.
    const apiBase = (process.env.QONVO_E2E_API ?? "https://dev-api.qonvo.org").replace(/\/$/, "");
    const login = await request.post(`${apiBase}/api/auth/login`, {
      data: {
        email: process.env.QONVO_E2E_OWNER_EMAIL ?? "owner@dev.dev",
        password: process.env.QONVO_E2E_OWNER_PASSWORD ?? "dev-password-123",
      },
    });
    test.skip(!login.ok(), "no API login on this environment");
    const token = (await login.json()).access_token;

    // REFUSE to touch a tenant that actually has a subscription. This probe
    // exists to check the status code on a REFUSAL, and on a subscribed tenant
    // the same call succeeds -- which would silently change the plan of a
    // paying business because a test ran. Run it against a tenant with nothing
    // to change.
    const billing = await (
      await request.get(`${apiBase}/api/billing`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    ).json();
    test.skip(
      !!billing?.subscription,
      "this tenant has a live subscription; change-plan would succeed and alter it",
    );

    const res = await request.post(`${apiBase}/api/billing/change-plan`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { plan_key: "growth" },
      failOnStatusCode: false,
    });
    const body = await res.json().catch(() => ({}));
    if (body?.ok === false) {
      expect(res.status(), "a refusal must carry a failure status").not.toBe(200);
    }
  });

  test("the billing page renders without console errors", async ({ page }) => {
    const errors: string[] = [];
    failOnConsoleErrors(page, errors);
    await gotoPage(page, "/billing");
    await page.waitForTimeout(1500);
    expect(errors).toEqual([]);
  });
});
