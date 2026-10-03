import { test, expect } from "@playwright/test";
import { gotoPage } from "../lib/app";

/**
 * Edit, save, reload, check it stuck, put it back.
 *
 * Both of these pages hide "Save changes" and "Discard" until something has
 * actually changed, which is good UX and the reason the first version of this
 * file skipped: it looked for Save before editing anything.
 *
 * The reply-language case is the one that matters most. `reply_language_mode`
 * was once omitted from the Behavior page's submitted fields while its own
 * card edited it, so choosing a reply language was silently dropped and the
 * page still said "Saved".
 */
async function saveChanges(page: import("@playwright/test").Page) {
  const save = page.getByRole("button", { name: /^save changes$/i });
  await expect(save, "editing must reveal a save control").toBeVisible({ timeout: 5000 });
  await save.click();
  await page.waitForTimeout(3500);
  const body = await page.locator("body").innerText();
  expect(body, "no raw body on save").not.toMatch(/\{"(ok|detail)"\s*:/);
}

test.describe("@settings @actions editing settings", () => {
  test("@smoke the reply-language choice actually persists", async ({ page }) => {
    await gotoPage(page, "/behavior");
    const select = page.locator("#reply-language-mode");
    await expect(select).toBeVisible();

    const original = await select.inputValue();
    const options = await select.locator("option").evaluateAll((os) =>
      os.map((o) => (o as HTMLOptionElement).value),
    );
    const other = options.find((o) => o && o !== original);
    test.skip(!other, "only one reply-language option");

    await select.selectOption(other!);
    await saveChanges(page);

    await page.reload();
    await page.waitForTimeout(2500);
    expect(
      await page.locator("#reply-language-mode").inputValue(),
      "the reply language must survive a reload, not be silently dropped",
    ).toBe(other);

    await page.locator("#reply-language-mode").selectOption(original);
    await saveChanges(page);
    await page.reload();
    await page.waitForTimeout(2500);
    expect(await page.locator("#reply-language-mode").inputValue()).toBe(original);
  });

  test("custom instructions survive a save and a reload", async ({ page }) => {
    await gotoPage(page, "/behavior");
    const box = page.locator("#custom-instructions");
    const original = await box.inputValue();
    const probe = `${original}\nE2E probe line ${Date.now()}`;

    await box.fill(probe);
    await saveChanges(page);
    await page.reload();
    await page.waitForTimeout(2500);
    expect(
      await page.locator("#custom-instructions").inputValue(),
      "the rules the rep answers from must persist exactly",
    ).toContain("E2E probe line");

    await page.locator("#custom-instructions").fill(original);
    await saveChanges(page);
    await page.reload();
    await page.waitForTimeout(2500);
    expect(
      await page.locator("#custom-instructions").inputValue(),
      "and must be restorable byte for byte",
    ).toBe(original);
  });

  test("Discard puts a change back without saving it", async ({ page }) => {
    await gotoPage(page, "/business");
    const name = page.locator("#business-name");
    const original = await name.inputValue();

    await name.fill(`${original} EDITED`);
    const discard = page.getByRole("button", { name: /^discard$/i });
    await expect(discard, "an edit must be abandonable").toBeVisible({ timeout: 5000 });
    await discard.click();
    await page.waitForTimeout(1500);
    expect(await name.inputValue(), "Discard must restore the original value").toBe(original);
  });

  test("the business name round-trips through a save", async ({ page }) => {
    await gotoPage(page, "/business");
    const name = page.locator("#business-name");
    const original = await name.inputValue();
    const probe = `${original} E2E`;

    await name.fill(probe);
    await saveChanges(page);
    await page.reload();
    await page.waitForTimeout(2500);
    expect(await page.locator("#business-name").inputValue()).toBe(probe);

    await page.locator("#business-name").fill(original);
    await saveChanges(page);
    await page.reload();
    await page.waitForTimeout(2500);
    expect(
      await page.locator("#business-name").inputValue(),
      "the business name must be left exactly as it was found",
    ).toBe(original);
  });

  test("nothing offers a save until something has changed", async ({ page }) => {
    await gotoPage(page, "/business");
    await expect(
      page.getByRole("button", { name: /^save changes$/i }),
      "an untouched form must not invite a pointless save",
    ).toHaveCount(0);
  });
});
