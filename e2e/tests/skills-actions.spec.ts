import { test, expect } from "@playwright/test";
import { gotoPage } from "../lib/app";

test.describe("@settings @actions skills and their gating", () => {
  test("@smoke a gated skill says what it needs, and links there", async ({ page }) => {
    await gotoPage(page, "/skills");
    const body = await page.locator("main").innerText();
    expect(body.trim().length).toBeGreaterThan(60);

    // The page's whole job when a skill cannot run is to say why and offer the
    // fix, rather than letting it fail silently in a conversation later.
    const links = page.locator("main a[href]");
    const n = await links.count();
    test.skip(n === 0, "nothing gated on this tenant");

    for (let i = 0; i < n; i++) {
      const href = await links.nth(i).getAttribute("href");
      const label = (await links.nth(i).textContent())?.trim() ?? "";
      expect(href, `"${label}" must point somewhere`).toBeTruthy();
      const res = await page.request.get(`${new URL(page.url()).origin}${href}`, {
        failOnStatusCode: false,
      });
      expect(res.status(), `the fix link for "${label}" must resolve`).toBeLessThan(400);
    }
  });

  test("following a gating link lands on the page that fixes it", async ({ page }) => {
    await gotoPage(page, "/skills");
    const link = page.locator("main a[href]").first();
    test.skip(!(await link.isVisible().catch(() => false)), "nothing gated");
    const label = (await link.textContent())?.trim() ?? "";
    await link.click();
    await page.waitForTimeout(3000);
    expect(page.url(), `"${label}" should navigate somewhere`).not.toContain("/skills");
    const body = await page.locator("main").innerText();
    expect(body.trim().length, "and the destination must render").toBeGreaterThan(60);
  });
});
