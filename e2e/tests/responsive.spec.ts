import { test, expect } from "@playwright/test";
import { gotoPage } from "../lib/app";

/**
 * Audit H3, 11 September: /knowledge rendered 922px wide at a 390px viewport,
 * taking the rep switch, the bell and the avatar off-screen. The tables were
 * already in overflow-x wrappers, which were correct and completely inert,
 * because a scroll container only scrolls once an ancestor has bounded it.
 *
 * One `min-w-0` fixed three pages. This is what stops it coming back.
 */
const PAGES = [
  "/inbox",
  "/analytics",
  "/knowledge",
  "/behavior",
  "/skills",
  "/integrations",
  "/business",
  "/team",
  "/billing",
  "/account",
];

test.describe("@responsive phone width", () => {
  for (const path of PAGES) {
    test(`${path} does not scroll sideways at phone width`, async ({ page }) => {
      await gotoPage(page, path);
      await page.waitForTimeout(600);
      const { doc, inner } = await page.evaluate(() => ({
        doc: document.documentElement.scrollWidth,
        inner: window.innerWidth,
      }));
      expect(doc, `${path} is ${doc}px wide in a ${inner}px viewport`).toBeLessThanOrEqual(inner + 1);
    });
  }

  test("the header controls stay on screen", async ({ page }) => {
    await gotoPage(page, "/knowledge");
    const offscreen = await page.evaluate(() => {
      const w = window.innerWidth;
      return Array.from(document.querySelectorAll("header button, header a"))
        .filter((el) => el.getBoundingClientRect().left > w)
        .length;
    });
    expect(offscreen, "header controls must not sit off the right edge").toBe(0);
  });
});
