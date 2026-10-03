import { test, expect } from "@playwright/test";
import { gotoPage, failOnConsoleErrors } from "../lib/app";

/**
 * Takeover is the promise that a human can always step in. The October audit
 * found a conversation sitting in paused_by_owner with nothing in the UI
 * explaining why or offering to release it.
 */
test.describe("@inbox inbox", () => {
  test("@smoke the inbox renders with its filters", async ({ page }) => {
    const errors: string[] = [];
    failOnConsoleErrors(page, errors);
    await gotoPage(page, "/inbox");
    const main = await page.locator("main").innerText();
    for (const filter of ["All", "Needs human", "Paused"]) {
      expect(main, `the ${filter} filter should be offered`).toContain(filter);
    }
    expect(errors).toEqual([]);
  });

  test("opening a conversation shows its transcript", async ({ page }) => {
    await gotoPage(page, "/inbox");
    await page.waitForTimeout(1200);
    const rows = page.locator("main li, main [role='listitem'], main button").filter({
      hasText: /\d|:/,
    });
    const count = await rows.count();
    test.skip(count === 0, "no conversations on this tenant");
    await rows.first().click().catch(() => {});
    await page.waitForTimeout(1500);
    const text = await page.locator("main").innerText();
    expect(text.trim().length).toBeGreaterThan(100);
  });

  test("a paused conversation offers a way back", async ({ page }) => {
    // A conversation sat in paused_by_owner through the October audit with
    // nothing in the UI saying why or offering to undo it. The state is only
    // useful if the interface both shows it and can reverse it.
    await gotoPage(page, "/inbox");
    await page.waitForTimeout(1200);
    const filter = page.getByRole("button", { name: /^Paused$/ });
    test.skip(!(await filter.isVisible().catch(() => false)), "no Paused filter on this build");
    await filter.click();
    await page.waitForTimeout(1800);

    const body = await page.locator("main").innerText();
    // The empty state is a pass: nothing is stuck. Keyword-matching the whole
    // page was wrong -- "Needs human" in the filter row matched it every time.
    test.skip(/no conversations yet/i.test(body), "no paused conversations to check");

    const rows = page.locator("main button").filter({ hasText: /\d{1,2} \w{3} \d{4}/ });
    test.skip((await rows.count()) === 0, "no paused conversations to check");
    await rows.first().click();
    await page.waitForTimeout(1500);
    const release = page.getByRole("button", { name: /release|hand back|resume|give back|let the rep/i });
    expect(
      await release.count(),
      "a paused conversation must offer a way back, or it is stuck for ever",
    ).toBeGreaterThan(0);
  });
});
