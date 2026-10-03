import { test, expect } from "@playwright/test";
import { gotoPage, watchConsole } from "../lib/app";

/**
 * Does the owner SEE the change, without reloading?
 *
 * The whole suite had a blind spot: every test called `page.reload()` before
 * asserting, which proves a change persisted and says nothing about whether
 * anyone saw it happen. Billing had been showing the previous state after
 * every plan change, cancel and resume for as long as it has existed, and no
 * test noticed because they all reloaded first.
 *
 * These never reload. They are deliberately generous about timing -- some of
 * these writes take a couple of seconds -- because the thing being caught is a
 * page that never catches up at all, not a page that is slow.
 */
const SETTLE = { timeout: 20_000 };

test.describe("@noreload the page keeps up", () => {
  test("@smoke knowledge: a new entry appears, and a deleted one goes", async ({ page }) => {
    const con = watchConsole(page);
    page.on("dialog", (d) => d.accept());
    await gotoPage(page, "/knowledge");

    const title = `NoReload ${Date.now()}`;
    await page.getByRole("button", { name: "Add entry", exact: true }).click();
    await page.waitForTimeout(1000);
    const dialog = page.getByRole("dialog");
    await dialog.locator("#entry-title").fill(title);
    await dialog
      .locator("#entry-content")
      .fill("Opening hours are nine to six, Monday to Saturday. ".repeat(6));
    await dialog.getByRole("button", { name: /add entry/i }).last().click();

    await expect(
      page.locator("main").getByText(title, { exact: false }),
      "a new source must appear without the owner reloading",
    ).toBeVisible(SETTLE);

    await page.getByRole("button", { name: new RegExp(`Delete ${title.slice(0, 16)}`, "i") }).click();
    await expect(
      page.locator("main").getByText(title, { exact: false }),
      "and a deleted one must leave, without reloading",
    ).toHaveCount(0, SETTLE);
    con.assertClean("adding and deleting a knowledge entry");
  });

  test("team: an invitation appears, and a revoked one goes", async ({ page }) => {
    const con = watchConsole(page);
    page.on("dialog", (d) => d.accept());
    await gotoPage(page, "/team");

    // A full plan refuses the invite, and that refusal is not what this is
    // testing -- so skip rather than fail on it.
    const seats = await page.locator("main").innerText();
    test.skip(/cannot invite anyone else|full\./i.test(seats), "no seat free on this plan");

    const email = `noreload+${Date.now()}@example.com`;
    await page.locator("#invite-email").fill(email);
    await page.getByRole("button", { name: /^send invite$/i }).click();

    await expect(
      page.locator("main").getByText(email, { exact: false }),
      "an invitation must appear without reloading",
    ).toBeVisible(SETTLE);

    const row = page.locator("main tr, main li, main [data-row]").filter({ hasText: email });
    const revoke = row.getByRole("button", { name: /revoke|cancel|remove/i }).first();
    if (await revoke.isVisible().catch(() => false)) {
      await revoke.click();
      await expect(
        page.locator("main").getByText(email, { exact: false }),
        "and a revoked one must go, without reloading",
      ).toHaveCount(0, SETTLE);
    }
    con.assertClean("inviting and revoking");
  });

  test("behavior: saving clears the unsaved state without reloading", async ({ page }) => {
    const con = watchConsole(page);
    await gotoPage(page, "/behavior");
    const box = page.locator("#custom-instructions");
    const original = await box.inputValue();

    await box.fill(`${original}\nNoReload probe`);
    const save = page.getByRole("button", { name: /^save changes$/i });
    await expect(save, "an edit must reveal a save").toBeVisible({ timeout: 5000 });
    await save.click();

    // The page's own signal that the write landed: the dirty controls go away.
    // If they linger, the owner cannot tell a saved form from an unsaved one.
    await expect(
      page.getByRole("button", { name: /^save changes$/i }),
      "after a successful save the unsaved-changes controls must clear themselves",
    ).toHaveCount(0, SETTLE);

    await box.fill(original);
    const again = page.getByRole("button", { name: /^save changes$/i });
    if (await again.isVisible().catch(() => false)) {
      await again.click();
      await expect(page.getByRole("button", { name: /^save changes$/i })).toHaveCount(0, SETTLE);
    }
    con.assertClean("saving behavior");
  });

  test("business: saving clears the unsaved state without reloading", async ({ page }) => {
    await gotoPage(page, "/business");
    const name = page.locator("#business-name");
    const original = await name.inputValue();

    await name.fill(`${original} NR`);
    await page.getByRole("button", { name: /^save changes$/i }).click();
    await expect(
      page.getByRole("button", { name: /^save changes$/i }),
      "the save must clear itself once the write lands",
    ).toHaveCount(0, SETTLE);

    await name.fill(original);
    const again = page.getByRole("button", { name: /^save changes$/i });
    if (await again.isVisible().catch(() => false)) {
      await again.click();
      await expect(page.getByRole("button", { name: /^save changes$/i })).toHaveCount(0, SETTLE);
    }
    expect(
      await page.locator("#business-name").inputValue(),
      "and the business name is left as it was found",
    ).toBe(original);
  });

  test("account: the saved name is reflected without reloading", async ({ page }) => {
    const con = watchConsole(page);
    await gotoPage(page, "/account");
    const name = page.locator("#full-name");
    const original = await name.inputValue();
    const probe = "E2E NoReload Name";

    try {
      await name.fill(probe);
      await page.getByRole("button", { name: /^save name$/i }).click();
      // Acknowledged somewhere other than the box the owner just typed into --
      // matching /name/ would pass on any page that has the word on it.
      await expect
        .poll(async () => page.locator("body").innerText(), {
          ...SETTLE,
          message: "saving a name must be acknowledged on the page",
        })
        .toMatch(/saved|updated|changed/i);
    } finally {
      await name.fill(original);
      await page
        .getByRole("button", { name: /^save name$/i })
        .click()
        .catch(() => {});
      await page.waitForTimeout(3000);
    }
    expect(
      await page.locator("#full-name").inputValue(),
      "the owner's name must be left exactly as it was found",
    ).toBe(original);
    con.assertClean("saving the account name");
  });
});
