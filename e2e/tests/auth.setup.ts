import { test as setup } from "@playwright/test";
import { signIn, dismissTour } from "../lib/app";

const FILE = "e2e/.auth/owner.json";

/** Sign in once; every other spec reuses the session. */
setup("authenticate as the owner", async ({ page }) => {
  await signIn(page);
  await dismissTour(page);
  await page.context().storageState({ path: FILE });
});
