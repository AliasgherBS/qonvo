# Landing Page and SEO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the four static landing sections with a ten-section, animated, brand-correct marketing page, and add the metadata, structured data, and AI-search surface that the spec calls for.

**Architecture:** Section components live one-per-file under `components/marketing/`, composed by `app/page.tsx`. Motion is isolated in `'use client'` leaf components so the page stays a Server Component. Three data modules (`lib/contact.ts`, `lib/site.ts`, `lib/faq.ts`) are single sources of truth, consumed by both the rendered page and the JSON-LD, so visible text and structured data cannot drift.

**Tech Stack:** Next.js 15 App Router, Tailwind v4, `motion/react`, `next/font`, App Router `robots.ts` / `sitemap.ts` / `opengraph-image.tsx`.

**Spec:** [`docs/superpowers/specs/2026-08-17-frontend-overhaul-design.md`](../specs/2026-08-17-frontend-overhaul-design.md)

## Global Constraints

- **Zero em dashes (`—`) and zero en dashes (`–`).** `npm run verify:brand` enforces it. This plan must drive the `no-dashes` count for `app/` and `components/marketing/` to zero.
- **No hex literals**, no contact details outside `lib/contact.ts`, no price figures anywhere.
- **No prices.** Pricing is undecided. The section states that it is paid and offers a contact route, nothing more.
- **No CRM claim.** Leads go to a Google Sheet. CRM sync is answered only in the FAQ, as roadmap.
- **No fabricated social proof.** No testimonials, no customer logos, no invented metrics.
- **Domain is never hardcoded.** Everything derives from `lib/site.ts`.
- Node via nvm: `export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh"`. Commands assume cwd `/home/aliasgher/qonvo/dashboard`.
- **Deploy order matters.** `npm run build` alone leaves the running dashboard broken. Always follow with the copy steps before respawning. This bit us once already.

## Design decisions

**The page is locked dark.** Not the spec's original light page with dark sections. Reasons, in order of weight:

1. The hero video's background samples `#07120D`, which is Ink. On a Paper page it reads as a dark rectangle pasted onto the layout. On an Ink page it blends into the section with no visible boundary.
2. The brand kit's "on dark" guidance is explicit: Signal Green for actions and highlights, Volt for the loudest CTA, keep the rest calm.
3. The design skill's Page Theme Lock forbids sections flipping theme mid-page. A light page with three dark sections violates it three times. A dark page with one deliberate light block uses the single permitted colour-block switch.

Lock is applied by putting `dark` on the page wrapper, which activates the existing `@custom-variant dark`, so it holds regardless of the user's theme toggle. The legal pages and the app keep respecting the toggle.

**Dials:** `VARIANCE 7 / MOTION 7 / DENSITY 4`.

**Constraint budget, checked at the end:** 10 sections, so at most 3 eyebrows (design uses 2), at most 1 marquee (uses 1), no 3 consecutive split layouts, at least 4 distinct layout families (uses 10).

## File Structure

| File | Responsibility |
|---|---|
| `lib/site.ts` | Site URL, name, tagline. Single source for canonical, OG, sitemap. |
| `lib/contact.ts` | WhatsApp number and email. Nothing else may hold these. |
| `lib/faq.ts` | FAQ questions and answers. Feeds both the section and FAQPage JSON-LD. |
| `components/marketing/reveal.tsx` | Client. Scroll-reveal and stagger primitives, reduced-motion aware. |
| `components/marketing/hero.tsx` | Section 1. Asymmetric split, video. |
| `components/marketing/cost-of-waiting.tsx` | Section 2. Full-bleed statement. |
| `components/marketing/answered.tsx` | Section 3. Split, mirrored. |
| `components/marketing/capabilities.tsx` | Section 4. Bento, 4 cells. |
| `components/marketing/voice.tsx` | Section 5. Full-width media. |
| `components/marketing/languages.tsx` | Section 6. Marquee. The one light block. |
| `components/marketing/how-it-works.tsx` | Section 7. Sticky steps. |
| `components/marketing/pricing.tsx` | Section 8. Single card, no figures. |
| `components/marketing/faq.tsx` | Section 9. Two-column list. |
| `components/marketing/closing-cta.tsx` | Section 10. Closing statement. |
| `components/marketing/structured-data.tsx` | JSON-LD emitter. |
| `app/page.tsx` | Composes the sections. Server Component. |
| `app/robots.ts`, `app/sitemap.ts`, `app/opengraph-image.tsx` | Crawl and social surface. |
| `public/llms.txt` | AI-search description. |

---

### Task 1: Data modules

**Files:** Create `lib/site.ts`, `lib/contact.ts`, `lib/faq.ts`. Modify `lib/legal.ts`.

**Interfaces:**
- Produces: `SITE` (`url`, `name`, `tagline`, `description`), `CONTACT` (`whatsapp`, `whatsappHref`, `email`, `emailHref`), `FAQ` (array of `{ q, a }`). Consumed by Tasks 3 through 12.

- [ ] **Step 1: `lib/site.ts`**

```ts
/**
 * Single source for anything that names or locates the site.
 *
 * The domain is not settled (qonvo.ai or qonvo.org), so nothing may hardcode
 * it. Set NEXT_PUBLIC_SITE_URL at build time; NEXT_PUBLIC_* is baked in during
 * `next build`, so a bare restart will not pick up a change.
 */
export const SITE = {
  url: process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3002",
  name: "Qonvo",
  tagline: "Never miss a customer again.",
  description:
    "Qonvo is an AI customer rep on your own WhatsApp number. It answers in seconds, day or night, in your customer's language, and books appointments, takes orders and logs leads.",
} as const;
```

- [ ] **Step 2: `lib/contact.ts`**

```ts
/**
 * The only place contact details may live. `npm run verify:brand` fails the
 * build if an email or phone number appears anywhere else.
 *
 * The WhatsApp line is answered by Qonvo itself, running the product with our
 * own knowledge loaded. That is deliberate: the contact button is a live demo,
 * and the copy says so rather than hiding it. Email is the human fallback.
 */
export const CONTACT = {
  whatsapp: "+92 319 4505305",
  whatsappHref: "https://wa.me/923194505305",
  email: "alihuzezzy@gmail.com",
  emailHref: "mailto:alihuzezzy@gmail.com",
} as const;
```

- [ ] **Step 3: `lib/faq.ts`**

Ten entries. The CRM and trial-cap answers carry information deliberately kept off the rest of the page.

```ts
/**
 * Rendered by components/marketing/faq.tsx and emitted as FAQPage JSON-LD from
 * the same array, so visible text and structured data cannot drift apart.
 *
 * Answers open with a direct one-sentence response before elaborating, which
 * is what makes them quotable by AI search.
 */
export const FAQ = [
  {
    q: "Does it use my own WhatsApp number?",
    a: "Yes. Qonvo connects to the number you already give customers, so nothing changes for them. You scan one QR code and keep using WhatsApp on your phone as normal.",
  },
  {
    q: "Can a customer tell they are talking to AI?",
    a: "It replies in your business's voice, in whatever language the customer wrote in. You choose the persona and tone, and you can say plainly that it is an assistant if you prefer.",
  },
  {
    q: "What happens when it does not know something?",
    a: "It says so rather than guessing. Qonvo answers from the knowledge you give it, and when a question falls outside that it hands the conversation to you.",
  },
  {
    q: "How do I take over a conversation?",
    a: "Just reply from your phone. Qonvo notices you have stepped in and goes quiet for that chat, so you never talk over each other. You can also take over from the inbox.",
  },
  {
    q: "Which languages does it handle?",
    a: "It detects the customer's language and replies in it. English, Urdu, Roman Urdu, Arabic, Hindi, Spanish and French all work today, by text or voice note.",
  },
  {
    q: "Can it book into my existing calendar?",
    a: "Yes, into Google Calendar. Qonvo checks when you are genuinely busy before offering a slot, so it will not double-book you, and it writes the confirmed booking straight to your calendar.",
  },
  {
    q: "Does Qonvo sync to my CRM?",
    a: "Not yet. Today Qonvo logs every lead to a Google Sheet you control, which you can import or connect to most CRMs. Direct sync is on the roadmap.",
  },
  {
    q: "What are the limits during the free trial?",
    a: "The trial runs 14 days or 300 customer messages, whichever comes first. No card required to start.",
  },
  {
    q: "How long does setup take?",
    a: "About a day, and no code. Connect the number, paste in your hours, prices and common questions, then send it a test message.",
  },
  {
    q: "Who can see my customer conversations?",
    a: "Only you and the people you invite. Each business's data is isolated at the database level, so no other Qonvo customer can reach your conversations.",
  },
] as const;
```

- [ ] **Step 4: Point `lib/legal.ts` at `lib/contact.ts`**

`lib/legal.ts` currently hardcodes the address twice, which is the source of the two remaining `contact-isolation` failures. Import `CONTACT` and reference `CONTACT.email` for both `contactEmail` and `privacyEmail`.

- [ ] **Step 5: Verify**

```bash
npm run build && node scripts/verify-brand.mjs 2>&1 | grep -c contact-isolation
```

Expected: build passes, `contact-isolation` count is 0.

- [ ] **Step 6: Commit**

```bash
git add dashboard/lib/site.ts dashboard/lib/contact.ts dashboard/lib/faq.ts dashboard/lib/legal.ts
git commit -m "feat(dashboard): add site, contact and FAQ data modules"
```

---

### Task 2: Motion primitives

**Files:** Create `components/marketing/reveal.tsx`.

**Interfaces:**
- Produces: `<Reveal>` (single element, fades and rises on enter), `<RevealGroup>` + `<RevealItem>` (staggered children), `<Marquee>` (continuous horizontal scroll). All honour `prefers-reduced-motion`.

- [ ] **Step 1: Write the primitives**

```tsx
"use client";

import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";

const EASE = [0.16, 1, 0.3, 1] as const;

/** One element rising into place as it enters the viewport. */
export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.25 }}
      transition={{ duration: 0.6, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

/** Parent for staggered children. Pair with RevealItem. */
export function RevealGroup({
  children,
  className,
  stagger = 0.08,
}: {
  children: ReactNode;
  className?: string;
  stagger?: number;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? false : "hidden"}
      whileInView="shown"
      viewport={{ once: true, amount: 0.2 }}
      variants={{ hidden: {}, shown: { transition: { staggerChildren: stagger } } }}
    >
      {children}
    </motion.div>
  );
}

export function RevealItem({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      variants={{
        hidden: { opacity: 0, y: 20 },
        shown: { opacity: 1, y: 0, transition: { duration: 0.55, ease: EASE } },
      }}
    >
      {children}
    </motion.div>
  );
}

/**
 * Continuous horizontal scroll. Duplicates its children once so the loop has
 * no visible seam. Under reduced motion it renders one static row instead,
 * because an endlessly moving strip is exactly what that setting is for.
 */
export function Marquee({
  children,
  speed = 32,
}: {
  children: ReactNode;
  speed?: number;
}) {
  const reduce = useReducedMotion();

  if (reduce) {
    return (
      <div className="flex flex-wrap justify-center gap-3">{children}</div>
    );
  }

  return (
    <div className="relative flex overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_12%,black_88%,transparent)]">
      {[0, 1].map((copy) => (
        <motion.div
          key={copy}
          className="flex shrink-0 items-center gap-3 pr-3"
          animate={{ x: ["0%", "-100%"] }}
          transition={{ duration: speed, ease: "linear", repeat: Infinity }}
          aria-hidden={copy === 1}
        >
          {children}
        </motion.div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

```bash
npm run build
```

Expected: success. A "Cannot find module 'motion/react'" error means Task 7 of the foundation plan did not run.

- [ ] **Step 3: Commit**

```bash
git add dashboard/components/marketing/reveal.tsx
git commit -m "feat(dashboard): add scroll-reveal and marquee motion primitives"
```

---

### Task 3: Hero

**Files:** Create `components/marketing/hero.tsx`.

Hero rules that are hard failures if broken: at most 4 text elements, headline at most 2 lines, subtext at most 20 words, CTAs visible without scrolling, top padding at most `pt-24`, and no trust strip or tagline under the CTAs.

Copy, 19 words of subtext:

- Headline: "Never miss a customer again."
- Subtext: "Qonvo answers on your WhatsApp number in seconds, day or night, then books the slot and logs the lead."
- CTAs: "Start free trial" primary, "Sign in" secondary.

The video is the fourth element and the visual. `muted`, `loop`, `playsInline`, `autoPlay`, `preload="metadata"`, poster `hero-poster.jpg`. Both sources, webm first so browsers that support it take the smaller file.

- [ ] **Step 1: Write the component**, splitting the grid 6/5 at `lg` with the copy left and the video right, video capped at roughly 420px wide and centred on mobile where it stacks below the copy.
- [ ] **Step 2:** Verify the video element carries `muted` and `playsInline`. Without both, mobile Safari refuses to autoplay and the hero shows a black box.
- [ ] **Step 3: Commit.**

---

### Task 4: Cost of waiting

**Files:** Create `components/marketing/cost-of-waiting.tsx`.

Full-bleed statement, no split, which breaks the layout family immediately after the hero.

- Headline: "It's 2 AM. A customer just messaged."
- Body: "By morning, they have booked somewhere else."
- Three items revealed on scroll, each a cost rather than a feature: "Replied 7 hours later", "Booked with a competitor", "Never replied at all".

Rendered as rows separated by a single hairline, not as three equal cards and not with a bottom border on every row.

- [ ] **Step 1:** Write it using `RevealGroup` and `RevealItem`.
- [ ] **Step 2:** Verify no decorative status dots. The design skill bans them by default and this section is where they are most tempting.
- [ ] **Step 3: Commit.**

---

### Task 5: Answered

**Files:** Create `components/marketing/answered.tsx`.

Split, mirrored from the hero, using `public/conversation.png` on the left and copy on the right.

- Headline: "Answered in seconds. Booked automatically."
- Body: "Qonvo reads the question, checks when you are genuinely free, offers the open slots and confirms the booking. Your customer installs nothing."

- [ ] **Step 1:** Write it. Image gets real `alt` text describing the exchange, not "screenshot".
- [ ] **Step 2: Commit.**

---

### Task 6: Capabilities bento

**Files:** Create `components/marketing/capabilities.tsx`.

Four cells for four items, no empty cells. Sizes vary: the first cell spans two columns, the remaining three are single. At least two cells carry real visual fill rather than text on a flat panel.

- Eyebrow (1 of 2 on the page): none here. Headline only.
- Headline: "It does not just chat. It does the work."

Cells:
1. "Answers from your own knowledge" / "Add your hours, prices and policies once. Qonvo answers from those, never from guesswork."
2. "Books appointments" / "Connect Google Calendar. Qonvo checks what is actually free, so it will not double-book you."
3. "Takes orders and logs leads" / "Every order and every lead lands in a Google Sheet you control."
4. "Hands over to you" / "When a conversation needs a person, Qonvo steps back and you reply from the inbox."

Cell 3 says Google Sheet, not CRM. This is the claim correction and it is not optional.

- [ ] **Step 1:** Write it as a CSS grid, `md:grid-cols-3`, first cell `md:col-span-2`.
- [ ] **Step 2:** Verify exactly four cells and no blank tile.
- [ ] **Step 3: Commit.**

---

### Task 7: Voice

**Files:** Create `components/marketing/voice.tsx`.

Full-width section, distinct from every other family on the page.

- Eyebrow (1 of 2): "Voice, not just text"
- Headline: "Send a voice note. Get one back."
- Body: "Qonvo understands voice messages and replies with one, in the same language your customer spoke."

Rendered with a waveform motif built from styled spans sized by a fixed array, not random values, so it is stable across renders. This is decoration, not a fake audio player, so it must not imply a playable file that does not exist.

- [ ] **Step 1:** Write it.
- [ ] **Step 2:** Verify there is no play button that does nothing. A dead control is worse than no control.
- [ ] **Step 3: Commit.**

---

### Task 8: Languages

**Files:** Create `components/marketing/languages.tsx`.

The one marquee, and the one deliberate light block on the dark page, matching how the promo video handles this beat.

- Headline: "Speaks every customer's language."
- Body: "It detects the language and replies in it, by text or voice."
- Marquee pills: Hello, مرحبا, السلام علیکم, Hola, नमस्ते, Bonjour, Olá, Merhaba.

The non-Latin strings are why the foundation plan added Noto fallbacks. Each pill carries `lang` so screen readers switch voice correctly.

- [ ] **Step 1:** Write it using `Marquee`.
- [ ] **Step 2:** Verify the Arabic, Urdu and Devanagari pills render with correct glyphs and are not tofu boxes.
- [ ] **Step 3: Commit.**

---

### Task 9: How it works

**Files:** Create `components/marketing/how-it-works.tsx`.

Three steps. The design skill bans "Step 1 / Step 2 / Step 3" labels: the step content is the label.

- Headline: "Live in a day. No code."
- Steps: "Connect WhatsApp" / "Scan one QR code with the number you already use." · "Teach it your business" / "Paste in your hours, prices and the questions you answer daily." · "Let it answer" / "Send it a test message, then let it work while you do."

Vertical staggered layout with a connecting rule, not three equal cards and not a sticky pin, since pinning three short steps costs scroll length for no gain.

- [ ] **Step 1:** Write it.
- [ ] **Step 2: Commit.**

---

### Task 10: Pricing

**Files:** Create `components/marketing/pricing.tsx`.

No figures anywhere. One card, not three towers.

- Headline: "Start free. Pay when it is working."
- Body: "Every plan includes the full product. Pricing depends on how many conversations you handle, so talk to us and we will size it with you."
- Included list, shipped features only: your own WhatsApp number, unlimited knowledge, text and voice replies, calendar booking, order and lead capture, human handover, inbox and analytics.
- Trial line: "14 days free. No card required."
- Primary CTA "Start free trial". Secondary "Message us on WhatsApp", with the email as a quieter link below.

The WhatsApp CTA leads with the demo framing: the number is answered by Qonvo itself.

- [ ] **Step 1:** Write it, sourcing both contact routes from `CONTACT`.
- [ ] **Step 2:** Verify `node scripts/verify-brand.mjs` reports no `no-prices` and no `contact-isolation` failures.
- [ ] **Step 3: Commit.**

---

### Task 11: FAQ and closing CTA

**Files:** Create `components/marketing/faq.tsx`, `components/marketing/closing-cta.tsx`.

FAQ is a two-column list rendered from `lib/faq.ts`, not an accordion, so the text is present in the DOM for crawlers and LLMs.

Closing CTA: headline "Never miss a customer again.", one primary CTA, nothing else. It deliberately repeats the hero headline as a bookend, which is a composition choice, not duplicate-CTA-intent.

- [ ] **Step 1:** Write both.
- [ ] **Step 2: Commit.**

---

### Task 12: Compose the page and lock the theme

**Files:** Modify `app/page.tsx`, `components/marketing-shell.tsx`.

- [ ] **Step 1:** Replace `app/page.tsx` with a Server Component composing the ten sections in order, wrapped in a `dark` container with an explicit `bg-background` so the lock holds regardless of the user's theme toggle.
- [ ] **Step 2:** Update `MarketingShell` so the landing nav and footer read correctly on Ink, and add the legal links to the footer.
- [ ] **Step 3:** Verify `/privacy` and `/terms` still respect the theme toggle and were not caught by the lock.
- [ ] **Step 4: Commit.**

---

### Task 13: Metadata, structured data, crawl and AIO

**Files:** Create `components/marketing/structured-data.tsx`, `app/robots.ts`, `app/sitemap.ts`, `app/opengraph-image.tsx`, `public/llms.txt`. Modify `app/layout.tsx`, `app/page.tsx`.

- [ ] **Step 1: Metadata.** Add `metadataBase: new URL(SITE.url)` to the root layout, plus `openGraph` and `twitter` blocks. Per-page `title` and `description` on the landing, privacy and terms routes.
- [ ] **Step 2: JSON-LD.** `SoftwareApplication` with `applicationCategory: "BusinessApplication"` and **no `offers` block**, since prices are undecided and a fabricated or zero price is worse than none. `Organization` in the layout. `FAQPage` generated from `lib/faq.ts`.
- [ ] **Step 3: `robots.ts` and `sitemap.ts`**, listing only the public routes and disallowing the app. Both derive from `SITE.url`.
- [ ] **Step 4: `opengraph-image.tsx`**, replacing the static `og-default.png` with an `ImageResponse` that renders the tagline in the real Bricolage face.
- [ ] **Step 5: `public/llms.txt`**, describing what Qonvo is, who it is for, what it does and what it does not do yet, including the CRM position.
- [ ] **Step 6: Verify** `/robots.txt`, `/sitemap.xml` and `/llms.txt` all return 200 and are not redirected by middleware. The foundation plan already added `txt` and `xml` to the matcher exclusion for exactly this.
- [ ] **Step 7: Commit.**

---

### Task 14: Copy sweep and final verification

- [ ] **Step 1:** Drive `no-dashes` to zero across `app/` and `components/`, rewriting rather than character-swapping where a sentence needs restructuring.
- [ ] **Step 2:** Run the full gate, build, lint and the backend suite.
- [ ] **Step 3:** Deploy in the correct order and screenshot at 1440, 768 and 375, plus one run with reduced motion forced, confirming the hero holds on its poster.
- [ ] **Step 4:** Walk the constraint budget: eyebrow count at most 3, exactly 1 marquee, no 3 consecutive splits, at least 4 layout families, every CTA label one-per-intent, no fabricated numbers or names.
- [ ] **Step 5: Commit.**

## Done when

- [ ] `verify:brand` reports zero failures across every gate.
- [ ] Build, lint and backend suite all pass.
- [ ] The hero video autoplays muted and loops, and holds on its poster under reduced motion.
- [ ] `/robots.txt`, `/sitemap.xml`, `/llms.txt` return 200.
- [ ] FAQ text is present in the served HTML without JavaScript.
- [ ] No price figure, no CRM claim, no fabricated testimonial anywhere on the page.
- [ ] Screenshots at 375, 768 and 1440 show no horizontal overflow.
