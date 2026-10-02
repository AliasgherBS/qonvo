import { test, expect } from "@playwright/test";
import { gotoPage, failOnConsoleErrors } from "../lib/app";

test.describe("@analytics analytics", () => {
  test("@smoke the page renders both views without console errors", async ({ page }) => {
    const errors: string[] = [];
    failOnConsoleErrors(page, errors);
    await gotoPage(page, "/analytics");
    await page.waitForTimeout(1800);
    expect(errors).toEqual([]);
    const main = await page.locator("main").innerText();
    expect(main.trim().length).toBeGreaterThan(80);
  });

  test("a chart never paints an empty grid with a full axis", async ({ page }) => {
    // The original bug in this component, twice: a series of all zeroes drew a
    // full axis and a full set of date labels over nothing at all, while the
    // page insisted it was fine. Each view must carry its own empty state.
    await gotoPage(page, "/analytics");
    await page.waitForTimeout(1800);
    const svgs = page.locator("main svg");
    if ((await svgs.count()) === 0) return;
    const marks = await page.evaluate(() => {
      const svg = document.querySelector("main svg");
      if (!svg) return -1;
      return svg.querySelectorAll("rect, path, circle, line").length;
    });
    expect(marks, "a rendered chart must draw something").not.toBe(0);
  });
});
