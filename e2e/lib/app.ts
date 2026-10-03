import { expect, type Page, type APIRequestContext } from "@playwright/test";

export const OWNER_EMAIL = process.env.QONVO_E2E_OWNER_EMAIL ?? "owner@dev.dev";
export const OWNER_PASSWORD = process.env.QONVO_E2E_OWNER_PASSWORD ?? "dev-password-123";

/**
 * Sign in through the real form.
 *
 * The 1.5s settle is not superstition: the page is server-rendered and the
 * submit handler is attached on hydration, so a fill-and-click that lands
 * first produces no request at all and the test fails looking like bad
 * credentials. That cost an afternoon during the October audit.
 */
export async function signIn(page: Page, email = OWNER_EMAIL, password = OWNER_PASSWORD) {
  await page.goto("/login", { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await page.fill("#email", email);
  await page.fill("#password", password);
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => !u.pathname.includes("/login"), { timeout: 30_000 });
}

/**
 * The product tour is modal and covers the whole page for a new tenant, so
 * every click beneath it times out with a confusing "intercepts pointer
 * events". Dismiss it before touching anything.
 */
export async function dismissTour(page: Page) {
  for (let i = 0; i < 6; i++) {
    const skip = page.getByRole("button", { name: /^Skip$/ });
    if (!(await skip.isVisible().catch(() => false))) return;
    await skip.click({ timeout: 3000 }).catch(() => {});
    await page.waitForTimeout(400);
  }
}

export async function gotoPage(page: Page, path: string) {
  await page.goto(path, { waitUntil: "networkidle" });
  await dismissTour(page);
}

/** A bearer token for assertions the UI gives no control for. */
export async function apiToken(request: APIRequestContext, base: string): Promise<string> {
  const res = await request.post(`${base.replace("//dev.", "//dev-api.").replace("//qonvo", "//api.qonvo")}/api/auth/login`, {
    data: { email: OWNER_EMAIL, password: OWNER_PASSWORD },
  });
  expect(res.ok()).toBeTruthy();
  return (await res.json()).access_token;
}

/** Fail the test on any console error, which is how silent breakage shows up. */
export function failOnConsoleErrors(page: Page, sink: string[]) {
  page.on("console", (m) => {
    if (m.type() === "error") sink.push(m.text().slice(0, 200));
  });
  page.on("pageerror", (e) => sink.push(`pageerror: ${e.message.slice(0, 200)}`));
}

/**
 * Collects console errors for the whole life of a page, so a test can assert
 * that an INTERACTION was clean and not merely that the page loaded clean.
 *
 * Load-time checking is what the first version of this suite did, and it is
 * the weaker half: the billing 502 that printed a response body at a customer
 * appeared only after a click.
 */
export function watchConsole(page: Page) {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text();
    // Chrome logs a generic line for every failed request; the useful signal is
    // the status, which the network assertion covers separately.
    if (/Failed to load resource/i.test(t)) return;
    errors.push(t.slice(0, 200));
  });
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message.slice(0, 200)}`));
  return {
    errors,
    /** Request failures worth failing a test over, as they happen. */
    assertClean(context: string) {
      if (errors.length) {
        throw new Error(`console errors during ${context}:\n  ${errors.join("\n  ")}`);
      }
    },
  };
}

/** Fails if any API call made during the test answered 5xx. */
export function watchServerErrors(page: Page) {
  const bad: string[] = [];
  page.on("response", (res) => {
    if (res.status() >= 500 && res.url().includes("/api/")) {
      bad.push(`${res.status()} ${res.request().method()} ${res.url().split("/api/")[1]}`);
    }
  });
  return bad;
}
