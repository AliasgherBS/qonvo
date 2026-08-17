# Frontend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the real Qonvo brand kit to the dashboard, correcting five wrong color tokens and two wrong typefaces, and produce the brand and video assets the landing rebuild depends on.

**Architecture:** Everything downstream reads from the `@theme` block in `app/globals.css` and the font variables in `app/layout.tsx`, so correcting those two places propagates brand-wide with no component edits. Assets are generated once from `Branding+Marketing/` and committed to `dashboard/public/`. A `verify-brand.mjs` script encodes the spec's pre-ship gates as an executable check, which gives every task a real red-to-green cycle in a project that has no test runner.

**Tech Stack:** Next.js 15 App Router, Tailwind v4, `next/font/google`, Node 20+, ffmpeg via `uv run --with imageio-ffmpeg` (no sudo, no system install).

**Spec:** [`docs/superpowers/specs/2026-08-17-frontend-overhaul-design.md`](../specs/2026-08-17-frontend-overhaul-design.md)

## Global Constraints

- **Brand colors, exact values.** Signal Green `#00C776`, Ink `#08130E`, Deep Forest `#0B3B2B`, Volt `#C6FF3D`, Paper `#F3EFE6`.
- **Typefaces.** Bricolage Grotesque for display, Manrope for body. Both are variable fonts, so `weight` is omitted in `next/font/google` to load the full axis.
- **Zero em dashes (`—`) and zero en dashes (`–`) in any file under `dashboard/app/` or `dashboard/components/`.** Plain hyphen only. This is the single most-violated rule in this project.
- **No hex color literal in any component file.** All color flows from tokens in `globals.css`.
- **No phone number or email address outside `lib/contact.ts`.**
- **No currency symbol or price figure anywhere under `dashboard/app/`.**
- **Work only inside `dashboard/`.** No backend, API, or database changes.
- **Volt is a spotlight, not a background.** At most one Volt element per viewport.
- Commands assume cwd `/home/aliasgher/qonvo/dashboard` unless stated otherwise.
- Node is provided by nvm: `export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh"` before any `npm` command.

## File Structure

| File | Responsibility |
|---|---|
| `dashboard/scripts/verify-brand.mjs` | Create. Executable form of the spec's pre-ship gates. |
| `dashboard/package.json` | Modify. Add `verify:brand` script, add `motion` dependency. |
| `dashboard/app/globals.css` | Modify. Corrected brand tokens, z-index scale, tinted shadows, font variable wiring. |
| `dashboard/app/layout.tsx` | Modify. Swap Geist for Bricolage Grotesque and Manrope. |
| `dashboard/components/logo.tsx` | Modify. Render the real mark instead of a CSS letter circle. |
| `dashboard/public/*` | Create. Logo files, favicons, OG image, hero video, poster, conversation still. |
| `dashboard/app/icon.png`, `apple-icon.png` | Create. App Router file-based icon convention. |

---

### Task 1: Brand verification script

Establishes the red-to-green cycle every later task uses. The script must FAIL on the current codebase, because the tokens are currently wrong. That failure is the point.

**Files:**
- Create: `dashboard/scripts/verify-brand.mjs`
- Modify: `dashboard/package.json`

**Interfaces:**
- Consumes: nothing.
- Produces: `npm run verify:brand`, exit code 0 when all gates pass and 1 otherwise. Every later task in this plan and both follow-on plans runs it.

- [ ] **Step 1: Write the verification script**

Create `dashboard/scripts/verify-brand.mjs`:

```js
#!/usr/bin/env node
// Executable form of the pre-ship gates in
// docs/superpowers/specs/2026-08-17-frontend-overhaul-design.md section 10.
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const failures = [];
const fail = (gate, detail) => failures.push(`[${gate}] ${detail}`);

function walk(dir, out = []) {
  if (!existsSync(dir)) return out;
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry === ".next") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

const SOURCE_DIRS = [join(ROOT, "app"), join(ROOT, "components"), join(ROOT, "lib")];
const sources = SOURCE_DIRS.flatMap((d) => walk(d)).filter((f) =>
  /\.(tsx?|css)$/.test(f),
);
const read = (f) => readFileSync(f, "utf8");
const rel = (f) => relative(ROOT, f);

// Gate 1: brand tokens present and exact.
const BRAND = {
  "Signal Green": "#00C776",
  Ink: "#08130E",
  "Deep Forest": "#0B3B2B",
  Volt: "#C6FF3D",
  Paper: "#F3EFE6",
};
const globalsPath = join(ROOT, "app/globals.css");
const globals = existsSync(globalsPath) ? read(globalsPath) : "";
for (const [name, hex] of Object.entries(BRAND)) {
  if (!globals.toLowerCase().includes(hex.toLowerCase())) {
    fail("brand-tokens", `${name} ${hex} missing from app/globals.css`);
  }
}

// Gate 2: no em dash or en dash in any source file.
for (const f of sources) {
  const lines = read(f).split("\n");
  lines.forEach((line, i) => {
    if (line.includes("—") || line.includes("–")) {
      fail("no-dashes", `${rel(f)}:${i + 1} contains an em or en dash`);
    }
  });
}

// Gate 3: no raw hex color outside globals.css.
for (const f of sources) {
  if (f.endsWith("globals.css")) continue;
  const lines = read(f).split("\n");
  lines.forEach((line, i) => {
    if (/#[0-9a-fA-F]{6}\b/.test(line)) {
      fail("no-raw-hex", `${rel(f)}:${i + 1} hardcodes a hex color`);
    }
  });
}

// Gate 4: contact details only in lib/contact.ts.
const EMAIL = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/;
const PHONE = /\+\d{7,}/;
for (const f of sources) {
  if (f.endsWith(join("lib", "contact.ts"))) continue;
  const lines = read(f).split("\n");
  lines.forEach((line, i) => {
    if (EMAIL.test(line) || PHONE.test(line)) {
      fail("contact-isolation", `${rel(f)}:${i + 1} inlines a contact detail`);
    }
  });
}

// Gate 5: no price figures under app/.
for (const f of sources) {
  if (!f.startsWith(join(ROOT, "app"))) continue;
  const lines = read(f).split("\n");
  lines.forEach((line, i) => {
    if (/[$£€]\s?\d/.test(line)) {
      fail("no-prices", `${rel(f)}:${i + 1} contains a price figure`);
    }
  });
}

if (failures.length) {
  console.error(`verify-brand: ${failures.length} failure(s)\n`);
  for (const f of failures) console.error("  " + f);
  process.exit(1);
}
console.log("verify-brand: all gates passed");
```

- [ ] **Step 2: Register the npm script**

In `dashboard/package.json`, add to `"scripts"`:

```json
"verify:brand": "node scripts/verify-brand.mjs"
```

- [ ] **Step 3: Run it and verify it FAILS**

```bash
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh"
cd ~/qonvo/dashboard && npm run verify:brand
```

Expected: exit code 1, with five `[brand-tokens]` failures naming Signal Green, Ink, Deep Forest, Volt, and Paper. There may also be `[no-dashes]` failures from existing copy. Both are correct: the gates are describing real defects that later tasks fix.

Record the failure count. Task 2 reduces it and Task 3 must not increase it.

- [ ] **Step 4: Commit**

```bash
git add dashboard/scripts/verify-brand.mjs dashboard/package.json
git commit -m "test(dashboard): add executable brand verification gates"
```

---

### Task 2: Correct the brand tokens

**Files:**
- Modify: `dashboard/app/globals.css:12-46` (the `@theme` block)

**Interfaces:**
- Consumes: `npm run verify:brand` from Task 1.
- Produces: corrected `--color-brand-*` custom properties. The `@theme inline` semantic layer below already maps them to `--color-primary`, `--color-background`, and so on, and no component hardcodes a hex, so this change propagates with zero component edits.

- [ ] **Step 1: Confirm the failing gate**

```bash
cd ~/qonvo/dashboard && npm run verify:brand 2>&1 | grep brand-tokens
```

Expected: five lines, one per brand color.

- [ ] **Step 2: Replace the palette**

In `app/globals.css`, replace the header comment and the `/* Brand palette */` values. Delete the "close approximations" comment entirely, it is now false.

```css
/*
 * Qonvo Brand Kit design tokens.
 *
 * Values extracted from `Branding+Marketing/Qonvo Brand Kit.pdf` section 02.
 * The five named brand colors are exact. Everything downstream reads from
 * these variables and nothing hardcodes a hex, which `npm run verify:brand`
 * enforces.
 */
@theme {
  /* Signal Green #00C776, primary. Actions and highlights. */
  --color-brand-primary-50: #e6f9f1;
  --color-brand-primary-100: #c0f0dc;
  --color-brand-primary-300: #5ce0ac;
  --color-brand-primary-400: #1fd28c;
  --color-brand-primary-500: #00c776;
  --color-brand-primary-600: #00a161;
  --color-brand-primary-700: #007c4b;
  --color-brand-primary-900: #04412a;

  /* Volt #C6FF3D, accent. A spotlight, not a background. */
  --color-brand-accent-200: #eeffbe;
  --color-brand-accent-300: #ddff8b;
  --color-brand-accent-500: #c6ff3d;
  --color-brand-accent-600: #a6dc1f;

  /* Deep Forest #0B3B2B surface, Ink #08130E text and dark ground. */
  --color-brand-surface-50: #f0f5f2;
  --color-brand-surface-100: #d9e6df;
  --color-brand-surface-700: #0b3b2b;
  --color-brand-surface-800: #092a1e;
  --color-brand-surface-900: #08130e;
  --color-brand-surface-950: #050d09;

  /* Paper #F3EFE6, light ground. */
  --color-brand-paper: #f3efe6;
  --color-brand-paper-dim: #e7e1d4;

  --font-sans: var(--font-body);
  --font-display: var(--font-display);
  --font-mono: var(--font-geist-mono);

  --radius-card: 1.25rem;
  --radius-pill: 999px;
}
```

Note the tint ramps around each brand color are derived, not from the kit, which specifies only the five named values. The five exact values appear at `primary-500`, `accent-500`, `surface-700`, `surface-900`, and `paper`.

- [ ] **Step 3: Run the gate and verify brand-tokens passes**

```bash
cd ~/qonvo/dashboard && npm run verify:brand 2>&1 | grep brand-tokens || echo "brand-tokens: PASS"
```

Expected: `brand-tokens: PASS`. Other gates may still fail, which later tasks address.

- [ ] **Step 4: Verify the build still compiles**

```bash
cd ~/qonvo/dashboard && npm run build
```

Expected: success. The `--font-body` and `--font-display` variables do not exist yet, so text falls back to the system stack until Task 3. That is expected and not an error.

- [ ] **Step 5: Commit**

```bash
git add dashboard/app/globals.css
git commit -m "fix(dashboard): use the real brand kit palette, not approximations"
```

---

### Task 3: Swap to the brand typefaces

**Files:**
- Modify: `dashboard/app/layout.tsx:1-42`
- Modify: `dashboard/app/globals.css` (the `@layer base` block)

**Interfaces:**
- Consumes: `--font-display` and `--font-sans` declared in the `@theme` block by Task 2.
- Produces: CSS variables `--font-display` (Bricolage Grotesque) and `--font-body` (Manrope) on `<html>`. Later plans use `font-display` and `font-sans` Tailwind utilities.

- [ ] **Step 1: Replace the font imports**

In `app/layout.tsx`, replace the Geist imports and constants. Both faces are variable fonts on Google Fonts, so `weight` is omitted deliberately to load the full axis rather than pinning discrete weights.

```tsx
import { Bricolage_Grotesque, Manrope, Geist_Mono } from "next/font/google";

const display = Bricolage_Grotesque({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-display",
});

const body = Manrope({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-body",
});

const mono = Geist_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-geist-mono",
});
```

Update the `<html>` className to use `display.variable`, `body.variable`, and `mono.variable` in place of the previous Geist variables. Keep every other attribute on that element, including the theme class handling, exactly as it is.

- [ ] **Step 2: Set the base type rules**

In `app/globals.css`, replace the `@layer base` heading rule. Manrope covers Latin only, so the stack names non-Latin fallbacks explicitly for the Arabic, Urdu, and Devanagari strings the landing page will render.

```css
@layer base {
  * {
    border-color: var(--border);
  }

  html {
    color-scheme: light dark;
  }

  body {
    background: var(--color-background);
    color: var(--color-foreground);
    /* Manrope is Latin-only. The Noto families cover the Arabic, Urdu and
       Devanagari greetings on the landing page and resolve from the system
       on every target platform, so they cost no extra download. */
    font-family: var(--font-body), "Noto Sans Arabic", "Noto Sans Devanagari",
      ui-sans-serif, system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
  }

  h1, h2, h3, h4 {
    font-family: var(--font-display), var(--font-body), ui-sans-serif, sans-serif;
    font-weight: 800;
    letter-spacing: -0.02em;
    text-wrap: balance;
  }

  p {
    text-wrap: pretty;
  }
}
```

- [ ] **Step 3: Build and verify**

```bash
cd ~/qonvo/dashboard && npm run build
```

Expected: success. A failure naming `Bricolage_Grotesque` means the font name is wrong; the `next/font/google` export uses underscores for spaces.

- [ ] **Step 4: Verify the fonts actually load in the browser**

Rebuild and restart per the deploy notes, which are mandatory in this project because `next start` does nothing under `output: "standalone"`:

```bash
cd ~/qonvo/dashboard && export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && \
  npm run build && \
  rm -rf .next/standalone/.next/static .next/standalone/public && \
  cp -r public .next/standalone/ && cp -r .next/static .next/standalone/.next/ && \
  tmux respawn-window -k -t qonvo:dashboard "~/qonvo/run-dashboard.sh 2>&1 | tee /tmp/qonvo-dashboard.log"
```

Open http://localhost:3002 and **hard refresh with Ctrl+Shift+R**, which is required because chunk hashes change on every rebuild. In devtools, confirm a heading computes to Bricolage Grotesque and body text computes to Manrope.

- [ ] **Step 5: Commit**

```bash
git add dashboard/app/layout.tsx dashboard/app/globals.css
git commit -m "feat(dashboard): adopt Bricolage Grotesque and Manrope per brand kit"
```

---

### Task 4: Brand assets into public/

`dashboard/public/` currently contains only `.gitkeep`. There is no favicon and no logo file anywhere in the app.

**Files:**
- Create: `dashboard/public/logo-mark.png`, `logo-mark-ink.png`, `og-default.png`
- Create: `dashboard/app/icon.png`, `dashboard/app/apple-icon.png`

**Interfaces:**
- Consumes: nothing.
- Produces: `/logo-mark.png` and `/logo-mark-ink.png` for Task 5. `/og-default.png` at 1200x630 for the SEO work in the landing plan. `app/icon.png` and `app/apple-icon.png` are picked up automatically by the App Router file convention, which needs no `<link>` tag.

- [ ] **Step 1: Copy the logo files**

```bash
cd ~/qonvo
cp "Branding+Marketing/logo/qonvo-logo-512.png"     dashboard/public/logo-mark.png
cp "Branding+Marketing/logo/qonvo-logo-1024.png"    dashboard/public/logo-mark-1024.png
cp "Branding+Marketing/logo/qonvo-logo-512-ink.png" dashboard/public/logo-mark-ink.png
cp "Branding+Marketing/logo/qonvo-logo-512.png"     dashboard/app/icon.png
cp "Branding+Marketing/logo/qonvo-logo-512.png"     dashboard/app/apple-icon.png
```

The 1024 copy is the high-density source for any future asset generation. It is not referenced by a component.

- [ ] **Step 2: Generate the OG image**

1200x630 on an Ink ground with the mark centered, built with the same ffmpeg binary the video task uses so there is no second toolchain:

```bash
cd ~/qonvo
FF=$(uv run --with imageio-ffmpeg python -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())" | tail -1)
"$FF" -hide_banner -loglevel error \
  -f lavfi -i "color=c=0x08130E:s=1200x630" \
  -i "Branding+Marketing/logo/qonvo-logo-512.png" \
  -filter_complex "[1]scale=260:260[m];[0][m]overlay=(W-w)/2:(H-h)/2-40" \
  -frames:v 1 dashboard/public/og-default.png -y
```

- [ ] **Step 3: Verify every file exists and has the right dimensions**

```bash
cd ~/qonvo && for f in dashboard/public/logo-mark.png dashboard/public/logo-mark-ink.png \
  dashboard/public/og-default.png dashboard/app/icon.png dashboard/app/apple-icon.png; do
  test -s "$f" && echo "OK $f $(file -b "$f" | cut -d, -f2)" || echo "MISSING $f"
done
```

Expected: five `OK` lines. `og-default.png` must report `1200 x 630`.

- [ ] **Step 4: Commit**

```bash
git add dashboard/public/ dashboard/app/icon.png dashboard/app/apple-icon.png
git commit -m "feat(dashboard): add brand logo, favicon and OG assets"
```

---

### Task 5: Rewrite the Logo component

`components/logo.tsx` currently renders a green circle containing the letter "Q". The real mark is a speech bubble holding a voice waveform, which is the whole brand idea: chat and voice, the two ways Qonvo talks.

**Files:**
- Modify: `dashboard/components/logo.tsx`

**Interfaces:**
- Consumes: `/logo-mark.png` and `/logo-mark-ink.png` from Task 4.
- Produces: `<Logo className?: string, showWordmark?: boolean />`. Default `showWordmark` is `true`. `components/sidebar.tsx:44` already calls `<Logo />` with no props and must keep working unchanged.

- [ ] **Step 1: Replace the component**

```tsx
import Image from "next/image";

import { cn } from "@/lib/utils";

export function Logo({
  className,
  showWordmark = true,
}: {
  className?: string;
  showWordmark?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      {/* The standard mark carries its own Signal Green tile, so it reads on
          Paper and on Ink alike. The ink variant is reserved for cases that
          need a single flat color. */}
      <Image
        src="/logo-mark.png"
        alt="Qonvo"
        width={28}
        height={28}
        className="h-7 w-7 rounded-lg"
        priority
      />
      {showWordmark ? (
        <span className="font-display text-lg font-extrabold lowercase tracking-tight">
          qonvo
        </span>
      ) : null}
    </span>
  );
}
```

The `@/lib/utils` specifier matches what the current file already imports, so the import line is unchanged from the version being replaced.

- [ ] **Step 2: Verify the build and the existing call site**

```bash
cd ~/qonvo/dashboard && npm run build && npm run lint
```

Expected: both succeed. `sidebar.tsx` calls `<Logo />` with no props, which still type-checks because both props are optional.

- [ ] **Step 3: Verify visually in both themes**

Rebuild and restart using the Task 3 Step 4 command, hard refresh, then confirm the sidebar shows the speech-bubble mark rather than a lettered circle, in both light and dark themes.

- [ ] **Step 4: Commit**

```bash
git add dashboard/components/logo.tsx
git commit -m "feat(dashboard): render the real brand mark instead of a letter circle"
```

---

### Task 6: Hero video and stills

The 55-second promo at `Branding+Marketing/Qonvo Promo Video.mp4` is 1920x1080, 30fps, and has **no audio stream**, which is what makes muted autoplay safe.

Three facts drive the edit, all verified against the source:

1. The booking sequence runs t=24.5 to t=37.0. At t=24.5 the phone shows only the customer's question, and by t=36.5 the full exchange including the voice note and the booking confirmation is on screen and holding.
2. The frame claiming "Logs the lead to your CRM" appears from t≈41. CRM sync is not shipped, so the loop must end before it. Ending at t=37.0 does.
3. Frames in this range carry burned-in headline text on the right half that would compete with the hero headline. Cropping to `608:1080:93:0` isolates the phone, yields a clean 9:16 portrait, and drops the burned-in copy. The background samples `#07120D`, which is Ink within video compression tolerance, so it blends into a dark hero section.

**Deviation from the spec, recorded deliberately.** Spec section 5.4 says "encode at 1280px wide", written before the crop was worked out. Cropping to the phone makes 608px the source width, and encoding at 1280 would upscale, inflating file size while adding no detail. 608x1080 is the correct output and supersedes that figure.

**Files:**
- Create: `dashboard/public/hero.mp4`, `hero.webm`, `hero-poster.jpg`, `conversation.png`

**Interfaces:**
- Consumes: nothing.
- Produces: `/hero.mp4` and `/hero.webm` at 608x1080, roughly 12.5s, silent, loopable. `/hero-poster.jpg` matches the video's first frame so there is no jump on play. `/conversation.png` shows the completed exchange for the static section in the landing plan.

- [ ] **Step 1: Resolve ffmpeg**

```bash
cd ~/qonvo
FF=$(uv run --with imageio-ffmpeg python -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())" | tail -1)
echo "$FF" && test -x "$FF" && echo "ffmpeg OK"
```

Expected: a path followed by `ffmpeg OK`. This needs no sudo and installs nothing system-wide.

- [ ] **Step 2: Encode the H.264 loop**

```bash
cd ~/qonvo
SRC="Branding+Marketing/Qonvo Promo Video.mp4"
"$FF" -hide_banner -loglevel error -ss 24.5 -t 12.5 -i "$SRC" \
  -vf "crop=608:1080:93:0" \
  -an -c:v libx264 -profile:v high -pix_fmt yuv420p -crf 26 \
  -movflags +faststart dashboard/public/hero.mp4 -y
```

`-an` strips audio explicitly, `-movflags +faststart` moves the index to the front so playback can begin before the file finishes downloading.

- [ ] **Step 3: Encode the VP9 loop**

```bash
cd ~/qonvo
"$FF" -hide_banner -loglevel error -ss 24.5 -t 12.5 -i "$SRC" \
  -vf "crop=608:1080:93:0" \
  -an -c:v libvpx-vp9 -crf 36 -b:v 0 -row-mt 1 \
  dashboard/public/hero.webm -y
```

- [ ] **Step 4: Extract the poster and the conversation still**

The poster is taken at the loop's first frame so the transition into playback is invisible. The conversation still is taken from the held completed state.

```bash
cd ~/qonvo
"$FF" -hide_banner -loglevel error -ss 24.5 -i "$SRC" \
  -vf "crop=608:1080:93:0" -frames:v 1 -q:v 4 \
  dashboard/public/hero-poster.jpg -y

"$FF" -hide_banner -loglevel error -ss 36.5 -i "$SRC" \
  -vf "crop=608:1080:93:0" -frames:v 1 \
  dashboard/public/conversation.png -y
```

- [ ] **Step 5: Verify size, duration, and absence of audio**

```bash
cd ~/qonvo/dashboard/public && ls -la hero.mp4 hero.webm hero-poster.jpg conversation.png
"$FF" -hide_banner -i hero.mp4 2>&1 | grep -E "Duration|Stream"
```

Expected: `hero.mp4` and `hero.webm` each **under 1.5MB**. Duration roughly `00:00:12.5`. Exactly one `Stream` line, a Video line reading `608x1080`. **An Audio stream line means Step 2 was run without `-an` and the file must be re-encoded**, since audio would block autoplay in every browser.

If either file exceeds 1.5MB, raise `-crf` by 2 and re-run that step.

- [ ] **Step 6: Confirm the CRM frame is absent**

```bash
cd ~/qonvo/dashboard/public
"$FF" -hide_banner -loglevel error -ss 12.0 -i hero.mp4 -frames:v 1 /tmp/hero-last.png -y
echo "Open /tmp/hero-last.png and confirm it shows the phone conversation, NOT the 'Logs the lead to your CRM' checklist."
```

This is a manual visual check and it matters: shipping that frame would put an unsupported claim on the landing page.

- [ ] **Step 7: Commit**

```bash
cd ~/qonvo
git add dashboard/public/hero.mp4 dashboard/public/hero.webm \
        dashboard/public/hero-poster.jpg dashboard/public/conversation.png
git commit -m "feat(dashboard): add hero video loop and stills from the promo"
```

---

### Task 7: Depth tokens and the motion dependency

**Files:**
- Modify: `dashboard/app/globals.css` (append to the `:root` and `.dark` blocks and the `@theme inline` block)
- Modify: `dashboard/package.json`

**Interfaces:**
- Consumes: brand tokens from Task 2.
- Produces: `--z-base`, `--z-sticky`, `--z-overlay`, `--z-modal`, `--z-toast` and `--shadow-sm|md|lg`. The `motion` package, imported as `motion/react` by the landing plan.

- [ ] **Step 1: Add the z-index and shadow scales**

Append inside the existing `:root` block in `app/globals.css`:

```css
  /* Documented z-index scale. Nothing may use an ad-hoc z value. */
  --z-base: 0;
  --z-sticky: 10;
  --z-overlay: 20;
  --z-modal: 30;
  --z-toast: 40;

  /* Shadows tinted toward Ink rather than pure black, so elevation reads as
     part of the palette instead of a grey wash. */
  --shadow-sm: 0 1px 2px 0 rgb(8 19 14 / 0.06);
  --shadow-md: 0 4px 12px -2px rgb(8 19 14 / 0.10);
  --shadow-lg: 0 18px 40px -12px rgb(8 19 14 / 0.22);
```

Append inside the existing `.dark` block, where shadows need more depth to register against a dark ground:

```css
  --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.30);
  --shadow-md: 0 4px 12px -2px rgb(0 0 0 / 0.40);
  --shadow-lg: 0 18px 40px -12px rgb(0 0 0 / 0.55);
```

Append inside the existing `@theme inline` block so the shadows become Tailwind utilities:

```css
  --shadow-sm: var(--shadow-sm);
  --shadow-md: var(--shadow-md);
  --shadow-lg: var(--shadow-lg);
```

- [ ] **Step 2: Install motion**

```bash
cd ~/qonvo/dashboard && export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && npm install motion
```

Import specifier is `motion/react`. The legacy `framer-motion` alias is not used.

- [ ] **Step 3: Verify build, lint, and all gates**

```bash
cd ~/qonvo/dashboard && npm run build && npm run lint && npm run verify:brand
```

Expected: all three succeed. `verify:brand` may still report `no-dashes` failures from existing landing and dashboard copy, which the two follow-on plans fix. Record the remaining count so the next plan can drive it to zero.

- [ ] **Step 4: Confirm no backend regression**

No backend file was touched, so this is a guard against accidental cross-boundary edits.

```bash
cd ~/qonvo/backend && uv run pytest -q && uv run ruff check
```

Expected: 211 passed, 6 skipped, and a clean ruff run.

- [ ] **Step 5: Commit**

```bash
cd ~/qonvo
git add dashboard/app/globals.css dashboard/package.json dashboard/package-lock.json
git commit -m "feat(dashboard): add z-index and tinted shadow scales, install motion"
```

---

## Done when

- [ ] `npm run verify:brand` reports zero `brand-tokens`, `no-raw-hex`, `contact-isolation`, and `no-prices` failures.
- [ ] `npm run build` and `npm run lint` both pass.
- [ ] Backend suite still reports 211 passed and 6 skipped.
- [ ] Headings render in Bricolage Grotesque and body in Manrope, confirmed in devtools.
- [ ] The sidebar shows the speech-bubble mark, correct in light and dark themes.
- [ ] `hero.mp4` and `hero.webm` are each under 1.5MB, silent, 608x1080, and contain no CRM frame.
- [ ] A favicon appears in the browser tab.

## Deliberately not in this plan

- Landing page sections, copy, and SEO. That is plan 2.
- Dashboard navigation, account routes, and the `tenant-config-form` split. That is plan 3.
- Remaining `no-dashes` failures in existing copy, fixed by plans 2 and 3 as each surface is rewritten.
- Re-rendering the promo video to correct the CRM claim and the baked-in `qonvo.ai` domain. Flagged in the spec, owned by whoever holds the video source.
