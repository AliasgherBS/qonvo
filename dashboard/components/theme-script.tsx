import { headers } from "next/headers";

/**
 * Runs before hydration to apply the persisted theme (or fall back to
 * prefers-color-scheme) without a flash of the wrong theme.
 */
const THEME_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem("qonvo-theme");
    var dark = stored === "dark" || (!stored && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", dark);
  } catch (e) {}
})();
`;

/**
 * Next stamps its own hydration bootstrap with the CSP nonce, but not ours, so
 * this reads it from the header middleware set and applies it.
 *
 * Without the nonce this script is blocked, and the failure is not subtle in
 * the way a blocked analytics beacon is: the page renders in the wrong theme
 * for a frame and then corrects itself, which is exactly the flash this
 * component exists to prevent.
 */
export async function ThemeScript() {
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return <script nonce={nonce} dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />;
}
