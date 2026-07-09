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

export function ThemeScript() {
  return <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />;
}
