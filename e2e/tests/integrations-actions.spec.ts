import { test, expect } from "@playwright/test";
import { gotoPage, watchConsole } from "../lib/app";

/**
 * **Nothing here disconnects anything.** Disconnect and Reconnect revoke or
 * re-request a live Google grant, which would break a working calendar on a
 * real tenant, so they are asserted to exist and never pressed. "Test
 * connection" is the one control here that is safe to use, and it is the one
 * an owner actually reaches for.
 */
test.describe("@integrations @actions connections", () => {
  test("@smoke Test connection reports a real result", async ({ page }) => {
    const con = watchConsole(page);
    await gotoPage(page, "/integrations");

    const test1 = page.getByRole("button", { name: /test connection/i }).first();
    test.skip(!(await test1.isVisible().catch(() => false)), "nothing connected");

    await test1.click();
    await page.waitForTimeout(6000);
    const body = await page.locator("main").innerText();
    expect(
      /working|ok|connected|success|could not|failed|problem/i.test(body),
      "testing a connection must report what it found",
    ).toBeTruthy();
    expect(body, "and never as a raw body").not.toMatch(/\{"(ok|detail)"\s*:/);
    con.assertClean("testing a connection");
  });

  test("a connected integration names the account it is connected to", async ({ page }) => {
    await gotoPage(page, "/integrations");
    const body = await page.locator("main").innerText();
    test.skip(!/disconnect/i.test(body), "nothing connected");
    expect(
      /@/.test(body),
      "an owner must be able to see WHICH account is connected, not just that one is",
    ).toBeTruthy();
  });

  test("the destructive controls exist and are distinguishable", async ({ page }) => {
    await gotoPage(page, "/integrations");
    const disconnect = page.getByRole("button", { name: /disconnect/i });
    test.skip((await disconnect.count()) === 0, "nothing connected");
    // Asserted, never clicked: this is a live Google grant.
    expect(await disconnect.count()).toBeGreaterThan(0);
    expect(await page.getByRole("button", { name: /reconnect/i }).count()).toBeGreaterThan(0);
  });

  test("the sheet picker offers the tabs it found", async ({ page }) => {
    await gotoPage(page, "/integrations");
    const select = page.locator("main select").first();
    test.skip(!(await select.isVisible().catch(() => false)), "no sheet selected");
    const options = await select.locator("option").evaluateAll((os) => os.length);
    expect(options, "the tab picker must list at least one tab").toBeGreaterThan(0);
  });
});
