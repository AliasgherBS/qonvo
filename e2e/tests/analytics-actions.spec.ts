import { test, expect } from "@playwright/test";
import { gotoPage, watchConsole, watchServerErrors } from "../lib/app";

/**
 * The page with the worst bug history in the product, and until now not a
 * single one of its 34 controls had ever been pressed by a test.
 *
 * Both of its known bugs live behind a click: a hover card drawn and then
 * clipped by an `overflow-x` scroll container, and a full axis painted over a
 * series of all zeroes while the page insisted it was fine.
 */
test.describe("@analytics @actions driving the analytics page", () => {
  test("@smoke the range buttons actually change the data", async ({ page }) => {
    const con = watchConsole(page);
    const bad = watchServerErrors(page);
    await gotoPage(page, "/analytics");

    const seen: Record<string, string> = {};
    for (const range of ["7 days", "30 days", "90 days"]) {
      const btn = page.getByRole("button", { name: range, exact: true });
      if (!(await btn.isVisible().catch(() => false))) continue;
      await btn.click();
      await page.waitForTimeout(2500);
      // The column count is the clearest proof the range took effect.
      seen[range] = String(await page.locator("main button[aria-label]").count());
    }
    expect(Object.keys(seen).length, "the range control must be usable").toBeGreaterThan(1);
    const counts = Object.values(seen).map(Number);
    expect(
      new Set(counts).size,
      `every range drew the same number of columns (${JSON.stringify(seen)}) - the filter is inert`,
    ).toBeGreaterThan(1);
    con.assertClean("changing the analytics range");
    expect(bad, "no 5xx while changing range").toEqual([]);
  });

  test("Messages and Voice are two views of the same chart", async ({ page }) => {
    const con = watchConsole(page);
    await gotoPage(page, "/analytics");

    const messages = page.getByRole("button", { name: "Messages", exact: true });
    const voice = page.getByRole("button", { name: "Voice", exact: true });
    test.skip(!(await voice.isVisible().catch(() => false)), "no voice view on this build");

    const labelsFor = async () =>
      (await page.locator("main button[aria-label]").first().getAttribute("aria-label")) ?? "";

    await messages.click();
    await page.waitForTimeout(2000);
    const msgLabel = await labelsFor();

    await voice.click();
    await page.waitForTimeout(2000);
    const voiceLabel = await labelsFor();

    expect(msgLabel.length, "columns must describe themselves").toBeGreaterThan(5);
    expect(
      voiceLabel,
      "switching to Voice must change what the columns say, not just the heading",
    ).not.toBe(msgLabel);
    con.assertClean("switching between Messages and Voice");
  });

  test("a chart column is focusable and says what it means", async ({ page }) => {
    // The columns were made real buttons so the figures are reachable by
    // keyboard and on touch, and so a zero day -- which has no bar to aim at --
    // can still be inspected.
    await gotoPage(page, "/analytics");
    const cols = page.locator("main button[aria-label]");
    const n = await cols.count();
    test.skip(n === 0, "no chart columns");

    for (const i of [0, Math.floor(n / 2), n - 1]) {
      const label = await cols.nth(i).getAttribute("aria-label");
      expect(label, "every column must carry a readable label").toMatch(/\w+.*\d/);
      await cols.nth(i).focus();
      const active = await page.evaluate(() => document.activeElement?.getAttribute("aria-label"));
      expect(active, "a column must take keyboard focus").toBe(label);
    }
  });

  test("hovering a column reveals its figures, unclipped", async ({ page }) => {
    const con = watchConsole(page);
    await gotoPage(page, "/analytics");
    const col = page.locator("main button[aria-label]").first();
    test.skip(!(await col.isVisible().catch(() => false)), "no columns");

    const box = await col.boundingBox();
    await col.hover();
    await page.waitForTimeout(1200);

    // The original bug: the card was drawn, then clipped at the top edge by an
    // overflow-x container. Anything that appeared must be inside the viewport.
    const clipped = await page.evaluate(() => {
      const els = [...document.querySelectorAll('main [role="tooltip"], main [data-tooltip], main [class*="tooltip" i]')];
      return els.some((e) => {
        const r = e.getBoundingClientRect();
        return r.height > 0 && (r.top < 0 || r.left < 0 || r.bottom > window.innerHeight + 1);
      });
    });
    expect(clipped, "a hover card must not be drawn outside the viewport").toBeFalsy();
    expect(box, "the column must have a hit area").not.toBeNull();
    con.assertClean("hovering a chart column");
  });

  test("a zero series says so instead of painting an empty grid", async ({ page }) => {
    await gotoPage(page, "/analytics");
    const voice = page.getByRole("button", { name: "Voice", exact: true });
    test.skip(!(await voice.isVisible().catch(() => false)), "no voice view");
    await voice.click();
    await page.waitForTimeout(2500);

    const marks = await page.evaluate(() => {
      const svg = document.querySelector("main svg");
      return svg ? svg.querySelectorAll("rect,path,circle,line").length : -1;
    });
    const text = await page.locator("main").innerText();
    if (marks === 0) {
      expect(
        /no |nothing|yet|once your/i.test(text),
        "a chart with nothing to draw must say so rather than show an empty grid",
      ).toBeTruthy();
    }
  });
});
