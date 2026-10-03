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

/**
 * Save the tenant's configuration over the API, and put it back afterwards.
 *
 * Restoring through the UI is not good enough, and this is not theoretical.
 * The no-reload tests edited `custom_instructions` and restored in a `finally`
 * -- but when an assertion failed early the restore ran against a page in an
 * unexpected state and quietly did nothing. The next run then read the probe
 * value as the "original", saw no change to make, and saved that. A live
 * tenant's 1,821 characters of grounding rules became the string
 * "E2E NoReload Instructions" on production, on a number that was answering
 * customers. It is the same shape as the September incident, caused by a test.
 *
 * The API is the reliable path: it does not depend on a button being visible
 * or a page being in the state the test expected.
 */
export async function withConfigRestored(
  request: import("@playwright/test").APIRequestContext,
  apiBase: string,
  body: () => Promise<void>,
) {
  const base = apiBase.replace(/\/$/, "");
  const login = await request.post(`${base}/api/auth/login`, {
    data: { email: OWNER_EMAIL, password: OWNER_PASSWORD },
    failOnStatusCode: false,
  });
  if (!login.ok()) throw new Error("could not sign in to snapshot the config");
  const token = (await login.json()).access_token;
  const auth = { Authorization: `Bearer ${token}` };

  const before = await (await request.get(`${base}/api/config`, { headers: auth })).json();
  try {
    await body();
  } finally {
    const now = await (await request.get(`${base}/api/config`, { headers: auth })).json();
    const payload: Record<string, unknown> = { version: now.version };
    for (const key of [
      "business_name",
      "custom_instructions",
      "persona",
      "tone",
      "primary_language",
      "timezone",
    ]) {
      if (before[key] !== null && before[key] !== undefined) payload[key] = before[key];
    }
    const res = await request.put(`${base}/api/config`, {
      headers: { ...auth, "content-type": "application/json" },
      data: payload,
      failOnStatusCode: false,
    });
    if (!res.ok()) {
      throw new Error(`FAILED TO RESTORE TENANT CONFIG (${res.status()}) - check it by hand`);
    }
  }
}

/**
 * Refuse to edit the configuration of a tenant whose rep is live, unless told
 * to. Those fields are what the rep answers customers from.
 */
export async function assertConfigWritesAllowed(
  request: import("@playwright/test").APIRequestContext,
  apiBase: string,
) {
  if (process.env.QONVO_E2E_ALLOW_CONFIG_WRITES === "1") return null;
  const base = apiBase.replace(/\/$/, "");
  const login = await request.post(`${base}/api/auth/login`, {
    data: { email: OWNER_EMAIL, password: OWNER_PASSWORD },
    failOnStatusCode: false,
  });
  if (!login.ok()) return "could not check whether the rep is live";
  const token = (await login.json()).access_token;
  const act = await request.get(`${base}/api/activation`, {
    headers: { Authorization: `Bearer ${token}` },
    failOnStatusCode: false,
  });
  if (!act.ok()) return null;
  const { rep_active } = await act.json();
  return rep_active
    ? "this tenant's rep is live; set QONVO_E2E_ALLOW_CONFIG_WRITES=1 to edit its configuration"
    : null;
}
