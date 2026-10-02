import { defineConfig, devices } from "@playwright/test";

/**
 * Targets STAGING by default, deliberately.
 *
 * These tests click real buttons against a real stack. Pointing them at
 * production by accident is the kind of mistake you only make once, so
 * production requires both QONVO_E2E_BASE and QONVO_E2E_ALLOW_PRODUCTION=1.
 */
const BASE = process.env.QONVO_E2E_BASE ?? "https://dev.qonvo.org";

if (BASE.includes("//qonvo.org") && process.env.QONVO_E2E_ALLOW_PRODUCTION !== "1") {
  throw new Error(
    "Refusing to run against production. Set QONVO_E2E_ALLOW_PRODUCTION=1 if you mean it.",
  );
}

export default defineConfig({
  testDir: "./tests",
  // One worker: every test shares one tenant, and parallel writes to the same
  // config row would make failures depend on scheduling rather than on code.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never" }], ["list"]]
    : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: BASE,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 15_000,
  },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], storageState: "e2e/.auth/owner.json" },
      dependencies: ["setup"],
    },
    {
      // The September audit found three pages rendering 922px wide at a 390px
      // viewport, with the header controls scrolled off. Phone width is a
      // first-class target here, not an afterthought.
      name: "phone",
      use: { ...devices["Pixel 7"], storageState: "e2e/.auth/owner.json" },
      dependencies: ["setup"],
      testMatch: /responsive\.spec\.ts/,
    },
  ],
});
