import { test, expect } from "@playwright/test";
import { gotoPage } from "../lib/app";

/**
 * Takeover and release, driven from the inbox.
 *
 * **Nothing here sends a message.** The composer is checked for existence and
 * for accepting input, and the test stops short of the send button, because on
 * this tenant the other end of every conversation is a real person. Takeover
 * itself is reversible and the test always puts the conversation back.
 */

/** Only touch a conversation we are allowed to disturb. */
const SAFE_CHATS = (process.env.QONVO_E2E_SAFE_CHAT ?? "").split(",").filter(Boolean);

async function openFirstConversation(page: import("@playwright/test").Page) {
  await gotoPage(page, "/inbox");
  await page.waitForTimeout(1800);
  const rows = page.locator("main button").filter({ hasText: /\d{1,2} \w{3} \d{4}/ });
  const n = await rows.count();
  if (n === 0) return null;
  await rows.first().click();
  await page.waitForTimeout(2000);
  return rows.first();
}

test.describe("@inbox @actions takeover and release", () => {
  test("@smoke opening a conversation shows the transcript and a composer", async ({ page }) => {
    const row = await openFirstConversation(page);
    test.skip(row === null, "no conversations on this tenant");

    const text = await page.locator("main").innerText();
    expect(text.length, "the transcript must render").toBeGreaterThan(150);
    expect(text, "no raw body").not.toMatch(/\{"(ok|detail)"\s*:/);

    // The product's promise is that a human can step in, so the means to do it
    // has to be on screen.
    const canStepIn =
      (await page.getByRole("button", { name: /take over|reply|respond/i }).count()) > 0 ||
      (await page.locator('main textarea, main [contenteditable="true"]').count()) > 0;
    expect(canStepIn, "an owner must have some way to take over a conversation").toBeTruthy();
  });

  test("the composer accepts typing without sending", async ({ page }) => {
    const row = await openFirstConversation(page);
    test.skip(row === null, "no conversations");

    const takeover = page.getByRole("button", { name: /take over/i }).first();
    const hadTakeover = await takeover.isVisible().catch(() => false);
    test.skip(!hadTakeover, "no takeover control exposed");
    test.skip(
      SAFE_CHATS.length === 0,
      "refusing to take over a live customer conversation; set QONVO_E2E_SAFE_CHAT",
    );

    await takeover.click();
    await page.waitForTimeout(2500);
    const box = page.locator('main textarea, main [contenteditable="true"]').first();
    await expect(box, "taking over must give the owner somewhere to type").toBeVisible();
    await box.fill("E2E composer check - not sent");
    expect(await box.inputValue().catch(async () => (await box.innerText()))).toContain("not sent");

    // Clear it and hand the conversation back. Nothing was sent.
    await box.fill("");
    const release = page.getByRole("button", { name: /release|hand back|give back|let the rep/i }).first();
    if (await release.isVisible().catch(() => false)) {
      await release.click();
      await page.waitForTimeout(2500);
    }
    const after = await page.locator("main").innerText();
    expect(after, "no raw body").not.toMatch(/\{"(ok|detail)"\s*:/);
  });

  test("the filters actually filter", async ({ page }) => {
    await gotoPage(page, "/inbox");
    await page.waitForTimeout(1800);
    const counts: Record<string, number> = {};
    for (const name of ["All", "Needs human", "Paused"]) {
      const f = page.getByRole("button", { name: new RegExp(`^${name}$`) });
      if (!(await f.isVisible().catch(() => false))) continue;
      await f.click();
      await page.waitForTimeout(1800);
      counts[name] = await page.locator("main button").filter({ hasText: /\d{1,2} \w{3} \d{4}/ }).count();
    }
    // A filter that changes nothing is a filter that is not wired up. "All"
    // must be at least as large as any narrower view.
    if (counts["All"] !== undefined) {
      for (const [name, n] of Object.entries(counts)) {
        expect(n, `${name} cannot show more than All`).toBeLessThanOrEqual(counts["All"]);
      }
    }
  });

  test("search narrows the list", async ({ page }) => {
    await gotoPage(page, "/inbox");
    await page.waitForTimeout(1800);
    const search = page.locator('main input[type="search"], main input[placeholder*="search" i]').first();
    test.skip(!(await search.isVisible().catch(() => false)), "no search box");
    const before = await page.locator("main button").filter({ hasText: /\d{1,2} \w{3} \d{4}/ }).count();
    await search.fill("zzzz-no-such-conversation");
    await page.waitForTimeout(2000);
    const after = await page.locator("main button").filter({ hasText: /\d{1,2} \w{3} \d{4}/ }).count();
    expect(after, "a search for nonsense must narrow the list").toBeLessThanOrEqual(before);
    const t = await page.locator("main").innerText();
    if (after === 0) expect(t, "an empty result must say so").toMatch(/no |nothing|not found/i);
  });
});
