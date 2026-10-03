import { test, expect } from "@playwright/test";
import { gotoPage } from "../lib/app";

test.describe("@account @actions the account page", () => {
  test("@smoke the display name round-trips", async ({ page }) => {
    await gotoPage(page, "/account");
    const name = page.locator("#full-name");
    const original = await name.inputValue();
    // An ABSOLUTE probe, not `${original} E2E`. Appending compounds: a run that
    // dies before restoring leaves the suffix, and the next run appends to
    // that. A real owner's name reached "Aliasghar NR E2E NR" exactly that way.
    const probe = "E2E Display Name";

    try {
      await name.fill(probe);
      await page.getByRole("button", { name: /^save name$/i }).click();
      await page.waitForTimeout(3000);
      await page.reload();
      await page.waitForTimeout(2500);
      expect(await page.locator("#full-name").inputValue()).toBe(probe);
    } finally {
      // Always, even when the assertion above threw.
      await page.locator("#full-name").fill(original);
      await page
        .getByRole("button", { name: /^save name$/i })
        .click()
        .catch(() => {});
      await page.waitForTimeout(3000);
    }

    await page.reload();
    await page.waitForTimeout(2500);
    expect(
      await page.locator("#full-name").inputValue(),
      "the owner's name must be left exactly as it was found",
    ).toBe(original);
  });

  test("changing a password requires the current one, and says so", async ({ page }) => {
    await gotoPage(page, "/account");
    await page.locator("#current-password").fill("definitely-not-the-password");
    await page.locator("#new-password").fill("Qx7-mVrt-2026-Lk");
    await page.locator("#confirm-password").fill("Qx7-mVrt-2026-Lk");
    await page.getByRole("button", { name: /^change password$/i }).click();
    await page.waitForTimeout(3500);

    const body = await page.locator("body").innerText();
    expect(
      /current password is incorrect|incorrect|does not match|wrong/i.test(body),
      "a wrong current password must be refused in words",
    ).toBeTruthy();
    expect(body, "and never as a raw body").not.toMatch(/\{"(ok|detail)"\s*:/);
  });

  test("a weak new password is refused with reasons", async ({ page }) => {
    await gotoPage(page, "/account");
    await page.locator("#new-password").fill("short");
    await page.waitForTimeout(1200);
    const body = await page.locator("body").innerText();
    expect(
      /12 characters|too short|at least/i.test(body),
      "the rules must be visible while typing, not after submitting",
    ).toBeTruthy();
  });

  test("two-factor and sign-out-everywhere are both offered", async ({ page }) => {
    await gotoPage(page, "/account");
    await expect(page.getByRole("button", { name: /two-factor/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /sign out everywhere/i })).toBeVisible();
  });
});
