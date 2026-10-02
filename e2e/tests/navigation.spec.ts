import { test, expect } from "@playwright/test";
import { gotoPage, failOnConsoleErrors } from "../lib/app";

/**
 * Every sidebar destination must resolve and render cleanly. Routes are read
 * from the sidebar rather than hard-coded: during the October audit a
 * hand-written path produced a phantom 404 finding, because the page lives at
 * /onboarding/connect and not at /whatsapp.
 */
test.describe("@smoke navigation", () => {
  test("every sidebar link resolves and renders", async ({ page }) => {
    const errors: string[] = [];
    failOnConsoleErrors(page, errors);
    await gotoPage(page, "/inbox");

    const hrefs = await page.evaluate(() =>
      Array.from(document.querySelectorAll("nav a[href], aside a[href]"))
        .map((a) => a.getAttribute("href"))
        .filter((h): h is string => !!h && h.startsWith("/")),
    );
    const unique = [...new Set(hrefs)];
    expect(unique.length, "the sidebar should offer several destinations").toBeGreaterThan(5);

    for (const href of unique) {
      const res = await page.goto(href, { waitUntil: "domcontentloaded" });
      expect(res?.status(), `${href} should resolve`).toBeLessThan(400);
      const text = await page.locator("body").innerText();
      expect(text.trim().length, `${href} should render something`).toBeGreaterThan(40);
    }
    expect(errors, "no console errors while walking the whole app").toEqual([]);
  });
});
