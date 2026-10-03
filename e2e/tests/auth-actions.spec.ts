import { test, expect } from "@playwright/test";
import { watchConsole, OWNER_EMAIL, OWNER_PASSWORD } from "../lib/app";

/**
 * The flows every single user goes through, and which the suite reached only
 * as a fixture. These run signed OUT, so they opt out of the stored session.
 */
test.use({ storageState: { cookies: [], origins: [] } });

test.describe("@auth @actions signed-out flows", () => {
  test("@smoke a wrong password is refused without saying which part was wrong", async ({ page }) => {
    const con = watchConsole(page);
    await page.goto("/login", { waitUntil: "networkidle" });
    await page.waitForTimeout(1500);
    await page.fill("#email", OWNER_EMAIL);
    await page.fill("#password", "definitely-not-the-password");
    await page.click('button[type="submit"]');
    await page.waitForTimeout(5000);

    expect(page.url(), "a bad password must not sign anyone in").toContain("/login");
    const body = await page.locator("body").innerText();
    // "Couldn't sign you in. Check your email and password and try again." --
    // the contraction is why an earlier version of this pattern missed it.
    expect(
      /couldn't|could not|cannot|incorrect|invalid|wrong|try again/i.test(body),
      "and must say so",
    ).toBeTruthy();
    // Enumeration: the message must not confirm the address exists.
    expect(
      /no account|unknown email|not registered|no such user/i.test(body),
      "the refusal must not tell an attacker whether the address exists",
    ).toBeFalsy();
    expect(body, "no raw body").not.toMatch(/\{"(ok|detail)"\s*:/);
    con.assertClean("a failed sign-in");
  });

  test("the right password signs you in and lands you somewhere useful", async ({ page }) => {
    await page.goto("/login", { waitUntil: "networkidle" });
    await page.waitForTimeout(1500);
    await page.fill("#email", OWNER_EMAIL);
    await page.fill("#password", OWNER_PASSWORD);
    await page.click('button[type="submit"]');
    await page.waitForURL((u) => !u.pathname.includes("/login"), { timeout: 30_000 });
    const body = await page.locator("body").innerText();
    expect(body.trim().length, "signing in must land on a real page").toBeGreaterThan(100);
  });

  test("forgot-password accepts an address without revealing whether it exists", async ({ page }) => {
    await page.goto("/forgot-password", { waitUntil: "networkidle" });
    await page.waitForTimeout(1500);
    const email = page.locator('input[type="email"], #email').first();
    test.skip(!(await email.isVisible().catch(() => false)), "no forgot-password form");

    await email.fill(`nobody-${Date.now()}@example.com`);
    await page.getByRole("button", { name: /send|reset|continue/i }).first().click();
    await page.waitForTimeout(4000);

    const body = await page.locator("body").innerText();
    expect(
      /check your (inbox|email)|if .* exists|sent|we have emailed/i.test(body),
      "it must acknowledge without confirming the address exists",
    ).toBeTruthy();
    expect(
      /no account|not found|unknown/i.test(body),
      "and must not leak that the address is unknown",
    ).toBeFalsy();
  });

  test("a protected page bounces a signed-out visitor to sign in", async ({ page }) => {
    await page.goto("/billing", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(4000);
    expect(page.url(), "a signed-out visitor must not reach billing").toContain("/login");
  });

  test("the signup form states its password rules before you submit", async ({ page }) => {
    await page.goto("/signup", { waitUntil: "networkidle" });
    await page.waitForTimeout(1500);
    await page.locator("#password").fill("short");
    await page.waitForTimeout(1000);
    const body = await page.locator("body").innerText();
    expect(
      /12 characters|at least/i.test(body),
      "the rules must be visible while typing, not discovered on submit",
    ).toBeTruthy();
  });
});
