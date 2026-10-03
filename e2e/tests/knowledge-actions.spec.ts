import { test, expect } from "@playwright/test";
import { gotoPage } from "../lib/app";

/**
 * Selectors here come from the live DOM, not from a guess about it. The first
 * version of this file skipped almost every test because it looked for a
 * generic "Add" button and a `#title` field; the page actually offers two
 * separate flows ("Add entry", "Add website"), a bare file input, and row
 * actions as icon buttons carrying aria-labels.
 */
const TITLE = `E2E entry ${Date.now()}`;

async function noRawBody(page: import("@playwright/test").Page) {
  const t = await page.locator("main").innerText();
  expect(t, "a response body was rendered to the owner").not.toMatch(/\{"(ok|detail)"\s*:/);
}

test.describe("@knowledge @actions adding and removing knowledge", () => {
  test("@smoke an owner can paste an entry, watch it go ready, and delete it", async ({ page }) => {
    await gotoPage(page, "/knowledge");

    await page.getByRole("button", { name: "Add entry", exact: true }).click();
    await page.waitForTimeout(1200);

    const dialog = page.getByRole("dialog");
    await expect(dialog, "Add entry must open a dialog").toBeVisible();
    // #entry-title and #entry-content, read from the live dialog. The first
    // version looked for a generic input[type=text] and timed out on the
    // dialog's own close button.
    await dialog.locator("#entry-title").fill(TITLE);
    await dialog
      .locator("#entry-content")
      .fill(
        "Opening hours are nine to six, Monday to Saturday. The refund window is " +
          "fourteen days from the date of treatment. ".repeat(4),
      );
    await dialog.getByRole("button", { name: /add entry|save|add$/i }).last().click();
    await page.waitForTimeout(4000);
    await noRawBody(page);

    await expect(
      page.locator("main").getByText(TITLE, { exact: false }),
      "an entry the owner just created must appear in their list",
    ).toBeVisible({ timeout: 20_000 });

    // It must reach a terminal state. A PDF sat on "Processing" for an entire
    // review round in September because the API and worker shared no volume.
    let ready = false;
    for (let i = 0; i < 18; i++) {
      await page.reload();
      await page.waitForTimeout(2500);
      const row = page.locator("main").locator("tr, li, div").filter({ hasText: TITLE }).first();
      const txt = await row.innerText().catch(() => "");
      if (/ready/i.test(txt)) { ready = true; break; }
      if (/error|failed/i.test(txt)) break;
    }
    expect(ready, "the entry must finish ingesting, not hang on Processing").toBeTruthy();

    // Delete it the way an owner would: the row's own icon button.
    const del = page.getByRole("button", { name: new RegExp(`Delete ${TITLE.slice(0, 18)}`, "i") });
    await expect(del, "each source must offer a delete control").toBeVisible();
    await del.click();
    await page.waitForTimeout(1200);
    const confirm = page.getByRole("button", { name: /^(delete|remove|confirm|yes)/i }).last();
    if (await confirm.isVisible().catch(() => false)) await confirm.click();
    await page.waitForTimeout(3000);
    await noRawBody(page);
    await expect(
      page.locator("main").getByText(TITLE, { exact: false }),
      "a deleted source must leave the list",
    ).toHaveCount(0, { timeout: 15_000 });
  });

  test("the Add website dialog validates and can be cancelled without saving", async ({ page }) => {
    await gotoPage(page, "/knowledge");
    const before = await page.locator("main").innerText();

    await page.getByRole("button", { name: "Add website", exact: true }).click();
    await page.waitForTimeout(1000);
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("#url-title"), "the website dialog asks for a title").toBeVisible();
    await expect(dialog.locator("#url-address"), "and for an address").toBeVisible();

    await dialog.getByRole("button", { name: /^cancel$/i }).click();
    await page.waitForTimeout(1200);
    await expect(dialog, "Cancel must close the dialog").toBeHidden();
    expect(
      (await page.locator("main").innerText()).length,
      "cancelling must not have added anything",
    ).toBe(before.length);
  });

  test("a refused address shows the reason, instead of a dialog that just sits there", async ({ page }) => {
    // Audit M7: the API refused a private address with a sentence written for a
    // human, and the dialog discarded it and stayed open with no explanation.
    await gotoPage(page, "/knowledge");
    await page.getByRole("button", { name: "Add website", exact: true }).click();
    await page.waitForTimeout(1000);
    const dialog = page.getByRole("dialog");
    await dialog.locator("#url-title").fill("E2E ssrf probe");
    await dialog.locator("#url-address").fill("http://169.254.169.254/latest/meta-data/");
    await dialog.getByRole("button", { name: /add website/i }).last().click();
    await page.waitForTimeout(4000);

    const shown = await page.locator("body").innerText();
    expect(
      /private network|cannot be reached|not allowed|invalid/i.test(shown),
      "the refusal must be shown to the owner, not swallowed",
    ).toBeTruthy();
    expect(shown, "and not as a raw body").not.toMatch(/\{"(ok|detail)"\s*:/);
  });

  test("the Sources and Gaps tabs both render", async ({ page }) => {
    await gotoPage(page, "/knowledge");
    for (const tab of ["Sources", "Gaps"]) {
      await page.getByRole("button", { name: tab, exact: true }).click();
      await page.waitForTimeout(1500);
      const t = await page.locator("main").innerText();
      expect(t.trim().length, `${tab} must render something`).toBeGreaterThan(60);
      expect(t).not.toMatch(/\{"(ok|detail)"\s*:/);
    }
  });
});
