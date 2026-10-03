import { test, expect } from "@playwright/test";
import {
  assertConfigWritesAllowed,
  gotoPage,
  watchConsole,
  withConfigRestored,
} from "../lib/app";

const API = (process.env.QONVO_E2E_API ?? "https://dev-api.qonvo.org").replace(/\/$/, "");

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

  test("behavior: saving clears the unsaved state without reloading", async ({ page, request }) => {
    const blocked = await assertConfigWritesAllowed(request, API);
    test.skip(!!blocked, blocked ?? "");
    await withConfigRestored(request, API, async () => {
    const con = watchConsole(page);
    await gotoPage(page, "/behavior");
    const box = page.locator("#custom-instructions");
    const original = await box.inputValue();

    await box.fill("E2E NoReload Instructions");
    const save = page.getByRole("button", { name: /^save changes$/i });
    await expect(save, "an edit must reveal a save").toBeVisible({ timeout: 5000 });
    await save.click();

    // The page's own signal that the write landed: the dirty controls go away.
    // If they linger, the owner cannot tell a saved form from an unsaved one.
    try {
      await expect(
        page.getByRole("button", { name: /^save changes$/i }),
        "after a successful save the unsaved-changes controls must clear themselves",
      ).toHaveCount(0, SETTLE);
    } finally {
      await box.fill(original);
      const again = page.getByRole("button", { name: /^save changes$/i });
      if (await again.isVisible().catch(() => false)) {
        await again.click();
        await page.waitForTimeout(3000);
      }
    }
    });
    con.assertClean("saving behavior");
  });

  test("business: saving clears the unsaved state without reloading", async ({ page, request }) => {
    const blocked = await assertConfigWritesAllowed(request, API);
    test.skip(!!blocked, blocked ?? "");
    await withConfigRestored(request, API, async () => {
    await gotoPage(page, "/business");
    const name = page.locator("#business-name");
    const original = await name.inputValue();
    // Absolute, never `${original} NR`. Appending compounds across runs: a
    // failed restore leaves the suffix and the next run appends to it. This
    // tenant's name reached "test01 NR NR NR NR" on production that way.
    const probe = "E2E NoReload Business";

    try {
      await name.fill(probe);
      await page.getByRole("button", { name: /^save changes$/i }).click();
      await expect(
        page.getByRole("button", { name: /^save changes$/i }),
        "the save must clear itself once the write lands",
      ).toHaveCount(0, SETTLE);
    } finally {
      await name.fill(original);
      const again = page.getByRole("button", { name: /^save changes$/i });
      if (await again.isVisible().catch(() => false)) {
        await again.click();
        await page.waitForTimeout(3000);
      }
    }
    });
  });

  test("account: the saved name is reflected without reloading", async ({ page, request }) => {
    // The owner's display name is their own, user-visible state, and this test
    // dirtied it twice on production before the restore was made reliable. It
    // carries the same opt-in as the config tests rather than a cleverer
    // restore: the value of the assertion does not justify editing a real
    // person's name on a live tenant by default.
    const blocked = await assertConfigWritesAllowed(request, API);
    test.skip(!!blocked, blocked ?? "");
    const con = watchConsole(page);
    await gotoPage(page, "/account");
    const name = page.locator("#full-name");
    const original = await name.inputValue();
    const probe = "E2E NoReload Name";

    try {
      await name.fill(probe);
      await page.getByRole("button", { name: /^save name$/i }).click();
      // The confirmation is a TOAST, and toasts dismiss themselves. Sampling
      // the page five seconds later found nothing and read exactly like a save
      // with no feedback at all -- poll from the moment of the click instead.
      //
      // Deliberately not asserting that the header updates: the avatar menu
      // reads the session JWT, which is minted at sign-in, and the toast says
      // so in as many words.
      await expect
        .poll(async () => page.locator("body").innerText(), {
          timeout: 10_000,
          intervals: [200, 200, 300, 500, 500, 1000],
          message: "saving a name must confirm itself",
        })
        .toMatch(/name saved|saved/i);
    } finally {
      await name.fill(original);
      // Only press it if it is pressable: this button disables itself when the
      // field matches what is stored, so a blind click waits out the timeout
      // and fails a test whose assertion had already passed.
      const save = page.getByRole("button", { name: /^save name$/i });
      if (await save.isEnabled().catch(() => false)) {
        await save.click().catch(() => {});
        await page.waitForTimeout(3000);
      }
    }
    expect(
      await page.locator("#full-name").inputValue(),
      "the owner's name must be left exactly as it was found",
    ).toBe(original);
    con.assertClean("saving the account name");
  });
});
