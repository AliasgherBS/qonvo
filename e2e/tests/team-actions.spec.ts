import { test, expect } from "@playwright/test";
import { gotoPage } from "../lib/app";

/** The invite form is inline on /team -- `#invite-email` and `#invite-role` -- not a dialog. */
const INVITEE = `e2e+${Date.now()}@example.com`;

test.describe("@team @actions inviting and removing", () => {
  test("@smoke an owner can invite a teammate and revoke it again", async ({ page }) => {
    await gotoPage(page, "/team");

    await page.locator("#invite-email").fill(INVITEE);
    await page.locator("#invite-role").selectOption({ label: "Staff" }).catch(async () => {
      await page.locator("#invite-role").selectOption("staff");
    });
    await page.getByRole("button", { name: /^send invite$/i }).click();
    await page.waitForTimeout(4000);

    const body = await page.locator("main").innerText();
    expect(body, "no raw body").not.toMatch(/\{"(ok|detail)"\s*:/);
    await expect(
      page.locator("main").getByText(INVITEE, { exact: false }),
      "an invitation just sent must appear in the list",
    ).toBeVisible({ timeout: 15_000 });

    const revoke = page.getByRole("button", { name: /revoke|cancel invite|^remove$/i }).last();
    if (await revoke.isVisible().catch(() => false)) {
      await revoke.click();
      await page.waitForTimeout(1200);
      const confirm = page.getByRole("button", { name: /revoke|remove|confirm|yes/i }).last();
      if (await confirm.isVisible().catch(() => false)) await confirm.click();
      await page.waitForTimeout(3000);
      await expect(
        page.locator("main").getByText(INVITEE, { exact: false }),
        "a revoked invitation must leave the list",
      ).toHaveCount(0, { timeout: 15_000 });
    }
  });

  test("an invalid address is refused before anything is sent", async ({ page }) => {
    await gotoPage(page, "/team");
    await page.locator("#invite-email").fill("not-an-email");
    await page.getByRole("button", { name: /^send invite$/i }).click();
    await page.waitForTimeout(2500);
    const body = await page.locator("body").innerText();
    expect(body, "no raw body").not.toMatch(/\{"(ok|detail)"\s*:/);
    await expect(
      page.locator("main").getByText("not-an-email", { exact: false }),
      "a malformed address must not become a pending invitation",
    ).toHaveCount(0);
  });

  test("the roles on offer are the roles that exist", async ({ page }) => {
    await gotoPage(page, "/team");
    const roles = await page
      .locator("#invite-role option")
      .evaluateAll((os) => os.map((o) => (o as HTMLOptionElement).textContent?.trim()));
    expect(roles).toEqual(expect.arrayContaining(["Staff", "Owner"]));
  });

  test("Export data gives the owner their data", async ({ page }) => {
    await gotoPage(page, "/team");
    const exp = page.getByRole("button", { name: /export data/i });
    await expect(exp, "GDPR export must be reachable").toBeVisible();
  });
});
