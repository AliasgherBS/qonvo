import { test as setup } from "@playwright/test";
import { signIn, dismissTour } from "../lib/app";

// Relative to the e2e package, which is where .gitignore's `.auth/` applies.
// It was "e2e/.auth/owner.json", which resolved to e2e/e2e/.auth and slipped
// past the ignore -- a live production session cookie, committed.
const FILE = ".auth/owner.json";

/** Sign in once; every other spec reuses the session. */
setup("authenticate as the owner", async ({ page }) => {
  await signIn(page);
  await dismissTour(page);
  await page.context().storageState({ path: FILE });
});
