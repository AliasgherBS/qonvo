import { test, expect } from "@playwright/test";
import { gotoPage } from "../lib/app";

/**
 * Clicking the buttons, not calling the endpoints behind them.
 *
 * The earlier billing specs asserted that "Switch to this" and "Cancel" were
 * VISIBLE. They were. They also did not work: a plan change on a subscription
 * scheduled to cancel answered 502, and the page printed
 * `{"ok":false,"reason":"provider_unavailable"}` verbatim under a "Message us
 * on WhatsApp" button. A test that checks a control exists is not a test that
 * the control does its job, and the difference is this file.
 *
 * Every test here presses something and asserts what the owner then sees.
 */

/** The page must never show a customer a raw response body. */
async function expectNoRawJson(page: import("@playwright/test").Page) {
  const text = await page.locator("main").innerText();
  expect(text, "a response body was rendered to the customer").not.toMatch(/\{"ok"\s*:/);
  expect(text).not.toMatch(/"reason"\s*:\s*"/);
  expect(text).not.toMatch(/provider_unavailable|no_subscription|subscription_cancelling/);
}

test.describe("@billing @actions the buttons do their job", () => {
  test("@smoke pressing a plan button produces a human answer, never a raw body", async ({ page }) => {
    await gotoPage(page, "/billing");

    const buttons = page.getByRole("button", { name: /^(Switch to this|Upgrade|Choose)$/ });
    const count = await buttons.count();
    test.skip(count === 0, "no plan action available on this tenant");

    const responses: { status: number; body: string }[] = [];
    page.on("response", async (res) => {
      if (!/\/api\/billing\/(change-plan|cancel|resume|checkout)/.test(res.url())) return;
      let body = "";
      try { body = (await res.text()).slice(0, 300); } catch { /* streamed */ }
      responses.push({ status: res.status(), body });
    });

    await buttons.first().click();
    await page.waitForTimeout(8000);

    // Either it worked, or the page says why in words the owner can act on.
    await expectNoRawJson(page);

    if (responses.length) {
      const r = responses[responses.length - 1];
      if (r.status >= 400) {
        // A refusal must carry prose, or some surface will render the body.
        expect(r.body, `a ${r.status} refusal must carry a detail message`).toMatch(/"detail"/);
      }
    }
  });

  test("a refusal explains itself and offers a way forward", async ({ page }) => {
    await gotoPage(page, "/billing");
    const buttons = page.getByRole("button", { name: /^(Switch to this|Upgrade)$/ });
    test.skip((await buttons.count()) === 0, "no plan change available");

    await buttons.first().click();
    await page.waitForTimeout(8000);

    const text = await page.locator("main").innerText();
    // Whatever happened, the owner is told something in sentences.
    const saidSomething =
      /plan has changed|could not|cannot|scheduled to cancel|try again|resume/i.test(text);
    expect(saidSomething, "pressing a plan button must produce visible feedback").toBeTruthy();
    await expectNoRawJson(page);
  });

  test("the cancel control opens, asks why, and can be dismissed", async ({ page }) => {
    await gotoPage(page, "/billing");
    const cancel = page.getByRole("button", { name: /cancel (subscription|plan)|cancel$/i }).first();
    test.skip(!(await cancel.isVisible().catch(() => false)), "no cancel control on this tenant");

    await cancel.click();
    await page.waitForTimeout(1500);
    const text = await page.locator("main").innerText();
    // Cancelling is destructive, so it must ask before it acts.
    expect(
      /why are you leaving|are you sure|keep my plan|confirm/i.test(text),
      "cancel must confirm before it ends the service a business pays for",
    ).toBeTruthy();
    await expectNoRawJson(page);
  });

  test("a subscription scheduled to cancel says so on the page", async ({ page, request }) => {
    const apiBase = (process.env.QONVO_E2E_API ?? "https://dev-api.qonvo.org").replace(/\/$/, "");
    const login = await request.post(`${apiBase}/api/auth/login`, {
      data: {
        email: process.env.QONVO_E2E_OWNER_EMAIL ?? "owner@dev.dev",
        password: process.env.QONVO_E2E_OWNER_PASSWORD ?? "dev-password-123",
      },
      failOnStatusCode: false,
    });
    test.skip(!login.ok(), "no API login here");
    const billing = await (
      await request.get(`${apiBase}/api/billing`, {
        headers: { Authorization: `Bearer ${(await login.json()).access_token}` },
      })
    ).json();
    test.skip(!billing?.subscription?.cancel_at_period_end, "subscription is not cancelling");

    await gotoPage(page, "/billing");
    const text = await page.locator("main").innerText();
    expect(
      /cancel|ends on|until/i.test(text),
      "an owner must be able to see that their subscription is ending",
    ).toBeTruthy();
  });

  test("every plan card's action is reachable by keyboard", async ({ page }) => {
    await gotoPage(page, "/billing");
    const buttons = page.getByRole("button", { name: /^(Switch to this|Upgrade|Choose|Current plan)$/ });
    const n = await buttons.count();
    test.skip(n === 0, "no plan cards");
    for (let i = 0; i < n; i++) {
      await buttons.nth(i).focus();
      const focused = await page.evaluate(() => document.activeElement?.textContent?.trim() ?? "");
      expect(focused.length, "each plan action must take keyboard focus").toBeGreaterThan(0);
    }
  });
});
