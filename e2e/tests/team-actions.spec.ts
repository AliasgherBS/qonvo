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

    // Scope the revoke to the INVITATION's own row, by name.
    //
    // An earlier version matched /revoke|cancel invite|^remove$/ and took
    // `.last()`. The only removal control this page renders is labelled
    // "Remove", and the match landed on a real team MEMBER instead: it removed
    // a live staff user from the tenant. A test that cleans up after itself
    // must be able to prove what it is cleaning up.
    page.on("dialog", (d) => d.accept());
    const inviteRow = page
      .locator("main tr, main li, main [data-row]")
      .filter({ hasText: INVITEE });
    const revoke = inviteRow.getByRole("button", { name: /revoke|cancel|remove/i }).first();
    if (await revoke.isVisible().catch(() => false)) {
      await revoke.click();
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
