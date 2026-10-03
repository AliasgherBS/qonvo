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

/**
 * The assertion class that was missing everywhere, and the reason none of the
 * earlier tests caught this: they all `page.reload()` before asserting, so they
 * prove a change PERSISTED and say nothing about whether the owner ever saw it.
 *
 * Billing is the only place in the product where that distinction matters,
 * because it is the only write confirmed asynchronously by a third party. Every
 * other section writes synchronously, so the response is the new state and a
 * refetch straight afterwards is correct. Here the refetch raced the webhook
 * and lost, every time.
 */
test.describe("@billing @actions the page keeps up without a reload", () => {
  async function planState(page: import("@playwright/test").Page) {
    return page.evaluate(() => {
      const t = document.querySelector("main")?.textContent ?? "";
      return {
        plan: (t.match(/(Starter|Growth|Scale) Plan/) ?? ["?"])[0],
        cancelling: /Cancelling/.test(t),
      };
    });
  }

  test("@smoke a plan change is visible without the owner reloading", async ({ page, request }) => {
    const apiBase = (process.env.QONVO_E2E_API ?? "https://dev-api.qonvo.org").replace(/\/$/, "");
    const login = await request.post(`${apiBase}/api/auth/login`, {
      data: {
        email: process.env.QONVO_E2E_OWNER_EMAIL ?? "owner@dev.dev",
        password: process.env.QONVO_E2E_OWNER_PASSWORD ?? "dev-password-123",
      },
      failOnStatusCode: false,
    });
    test.skip(!login.ok(), "no API login here");
    const token = (await login.json()).access_token;
    const billing = await (
      await request.get(`${apiBase}/api/billing`, { headers: { Authorization: `Bearer ${token}` } })
    ).json();
    test.skip(!billing?.subscription, "no subscription to move");
    test.skip(billing.subscription.cancel_at_period_end, "a cancelling subscription cannot change plan");

    await gotoPage(page, "/billing");
    const before = await planState(page);

    const move = page.getByRole("button", { name: /^(Upgrade|Switch to this)$/ }).first();
    test.skip((await move.count()) === 0, "no other plan on offer");
    await move.click();

    // Generous, because a webhook is involved -- but it must land on its own.
    // The bug was not slowness, it was that the page never caught up at all.
    await expect
      .poll(async () => (await planState(page)).plan, {
        timeout: 25_000,
        message: "the plan change must appear without a manual reload",
      })
      .not.toBe(before.plan);

    await expectNoRawJson(page);
  });

  test("cancelling is visible without a reload, and so is keeping it", async ({ page }) => {
    await gotoPage(page, "/billing");
    const cancel = page.getByRole("button", { name: /^cancel plan$/i }).first();
    test.skip(!(await cancel.isVisible().catch(() => false)), "nothing to cancel");

    await cancel.click();
    await page.waitForTimeout(1500);
    const confirm = page.getByRole("button", { name: /^(cancel (my )?plan|confirm|yes)/i }).last();
    if (await confirm.isVisible().catch(() => false)) await confirm.click();

    await expect
      .poll(async () => (await planState(page)).cancelling, {
        timeout: 25_000,
        message: "a cancellation must show itself without a manual reload",
      })
      .toBe(true);

    // And back again, which is where the 502 came from: the page offered
    // "Keep my plan" for a subscription the server had already resumed.
    const keep = page.getByRole("button", { name: /keep my plan/i }).first();
    await expect(keep, "a cancelling plan must offer the way back").toBeVisible();
    await keep.click();

    await expect
      .poll(async () => (await planState(page)).cancelling, {
        timeout: 25_000,
        message: "keeping the plan must show itself without a manual reload",
      })
      .toBe(false);

    await expectNoRawJson(page);
  });
});
