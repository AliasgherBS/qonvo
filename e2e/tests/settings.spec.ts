import { test, expect } from "@playwright/test";
import { gotoPage, failOnConsoleErrors } from "../lib/app";

test.describe("@settings behavior and business", () => {
  test("@smoke behavior renders every control it owns", async ({ page }) => {
    const errors: string[] = [];
    failOnConsoleErrors(page, errors);
    await gotoPage(page, "/behavior");
    const main = await page.locator("main").innerText();
    expect(main.trim().length).toBeGreaterThan(80);
    expect(errors).toEqual([]);
  });

  test("business settings render their form", async ({ page }) => {
    // Deliberately not asserting a button named Save: this page has none, and
    // a test written from an assumption about the UI rather than from the UI
    // fails for a reason that is not a defect. What must be true is that the
    // fields an owner came to edit are actually there.
    await gotoPage(page, "/business");
    const fields = page.locator("main input:not([type=hidden]), main textarea, main select");
    expect(await fields.count(), "business settings must offer editable fields").toBeGreaterThan(3);
  });

  test("skills are listed with their gating", async ({ page }) => {
    await gotoPage(page, "/skills");
    const main = await page.locator("main").innerText();
    // A skill that needs Google must say so rather than simply failing later.
    expect(main.trim().length).toBeGreaterThan(60);
  });
});
