import { test, expect } from "@playwright/test";
import { gotoPage, watchConsole } from "../lib/app";

/**
 * The opening-hours grid: 7 day switches, 14 time inputs and two copy buttons,
 * none of which a test had ever touched. These decide whether the rep answers
 * at all, and the timezone they are read in was wrong for a whole release
 * (B1/N1 -- hours evaluated in UTC, bookings five hours out).
 *
 * Everything here restores what it changed.
 */
async function save(page: import("@playwright/test").Page) {
  const btn = page.getByRole("button", { name: /^save changes$/i });
  await expect(btn, "an edit must reveal a save").toBeVisible({ timeout: 5000 });
  await btn.click();
  await page.waitForTimeout(3500);
  const body = await page.locator("body").innerText();
  expect(body, "no raw body on save").not.toMatch(/\{"(ok|detail)"\s*:/);
  // Saving must not silently fail, which is exactly what this page did until
  // v0.15.0: a 422 on two untouched fields, and the value reverting on reload.
  expect(
    /saved|up to date/i.test(body) || !(await btn.isVisible().catch(() => false)),
    "a save must either confirm or clear itself, never fail silently",
  ).toBeTruthy();
}

/**
 * The grid is deliberately inert while "Enforce opening hours" is off -- the
 * master-switch test below asserts exactly that -- so anything editing the
 * hours has to turn enforcement on first and put it back afterwards. Three of
 * these tests failed on a disabled control before that was understood.
 */
async function withEnforcementOn(
  page: import("@playwright/test").Page,
  body: () => Promise<void>,
) {
  const master = page.getByRole("switch", { name: /enforce opening hours/i });
  const was = (await master.getAttribute("aria-checked")) === "true";
  if (!was) {
    await master.click();
    await page.waitForTimeout(800);
  }
  try {
    await body();
  } finally {
    const now = page.getByRole("switch", { name: /enforce opening hours/i });
    const isOn = (await now.getAttribute("aria-checked").catch(() => null)) === "true";
    if (isOn !== was) {
      await now.click().catch(() => {});
      await page.waitForTimeout(600);
      await page
        .getByRole("button", { name: /^save changes$/i })
        .click()
        .catch(() => {});
      await page.waitForTimeout(2500);
    }
  }
}

test.describe("@settings @actions opening hours", () => {
  test("@smoke a day can be closed, saved, and reopened", async ({ page }) => {
    const con = watchConsole(page);
    await gotoPage(page, "/business");

    await withEnforcementOn(page, async () => {
    const sun = page.getByRole("switch", { name: /sun open/i });
    await expect(sun, "each day must have its own switch").toBeVisible();
    const before = await sun.getAttribute("aria-checked");

    await sun.click();
    await page.waitForTimeout(600);
    expect(await sun.getAttribute("aria-checked"), "the switch must move").not.toBe(before);
    await save(page);

    await page.reload();
    await page.waitForTimeout(2500);
    const persisted = await page.getByRole("switch", { name: /sun open/i }).getAttribute("aria-checked");
    expect(persisted, "closing a day must survive a reload").not.toBe(before);

    await page.getByRole("switch", { name: /sun open/i }).click();
    await page.waitForTimeout(600);
    await save(page);
    await page.reload();
    await page.waitForTimeout(2500);
    expect(
      await page.getByRole("switch", { name: /sun open/i }).getAttribute("aria-checked"),
      "the day must be left as it was found",
    ).toBe(before);
    });
    con.assertClean("editing opening hours");
  });

  test("a time can be changed and comes back the same", async ({ page }) => {
    await gotoPage(page, "/business");
    await withEnforcementOn(page, async () => {
    const first = page.locator("main input[type=time]").first();
    const original = await first.inputValue();
    const probe = original === "08:15" ? "08:45" : "08:15";

    await first.fill(probe);
    await page.waitForTimeout(500);
    await save(page);
    await page.reload();
    await page.waitForTimeout(2500);
    expect(
      await page.locator("main input[type=time]").first().inputValue(),
      "an opening time must persist exactly",
    ).toBe(probe);

    await page.locator("main input[type=time]").first().fill(original);
    await save(page);
    await page.reload();
    await page.waitForTimeout(2500);
    expect(await page.locator("main input[type=time]").first().inputValue()).toBe(original);
    });
  });

  test("Copy Monday to all days does what it says", async ({ page }) => {
    await gotoPage(page, "/business");
    await withEnforcementOn(page, async () => {
    const times = page.locator("main input[type=time]");
    const originals = await times.evaluateAll((els) =>
      els.map((e) => (e as HTMLInputElement).value),
    );

    const mondayOpen = originals[0];
    await page.getByRole("button", { name: /copy monday to all days/i }).click();
    await page.waitForTimeout(1200);

    const after = await times.evaluateAll((els) => els.map((e) => (e as HTMLInputElement).value));
    const opens = after.filter((_, i) => i % 2 === 0);
    expect(
      opens.every((v) => v === mondayOpen),
      `every day's opening time should now be Monday's (${mondayOpen}), got ${JSON.stringify(opens)}`,
    ).toBeTruthy();

    // Abandon it rather than save -- nothing here needs to persist.
    await page.getByRole("button", { name: /^discard$/i }).click();
    await page.waitForTimeout(1200);
    const restored = await times.evaluateAll((els) => els.map((e) => (e as HTMLInputElement).value));
    expect(restored, "Discard must put every day back").toEqual(originals);
    });
  });

  test("the enforce-hours master switch disables the grid rather than hiding it", async ({ page }) => {
    // Teardown B2: the master switch used to look off while every field under
    // it stayed live, so an owner could edit, save, and change nothing.
    await gotoPage(page, "/business");
    const master = page.getByRole("switch", { name: /enforce opening hours/i });
    await expect(master).toBeVisible();
    const on = (await master.getAttribute("aria-checked")) === "true";

    const firstTime = page.locator("main input[type=time]").first();
    const enabled = await firstTime.isEnabled();
    expect(
      enabled,
      on
        ? "with enforcement on, the hours must be editable"
        : "with enforcement off, the hours must be visibly inert, not quietly live",
    ).toBe(on);
  });
});
