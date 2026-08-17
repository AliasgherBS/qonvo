# Qonvo frontend overhaul: design

**Date:** 2026-08-17
**Status:** awaiting review
**Scope:** `dashboard/` only. No backend or API changes.

## 1. Why

The dashboard was built before the brand kit was applied and it shows. Three
concrete problems, all verified against the code:

1. **The brand kit was never applied.** [`app/globals.css`](../../../dashboard/app/globals.css)
   states in its own header comment that the palette is a set of "close
   approximations" pending extraction from `Branding+Marketing/Qonvo Brand
   Kit.pdf`. The extraction never happened. Five of five brand colors are wrong,
   and both brand typefaces are absent.
2. **Settings is a dumping ground.** [`components/tenant-config-form.tsx`](../../../dashboard/components/tenant-config-form.tsx)
   puts six unrelated concerns on one scroll: business persona, business hours,
   escalation, payments, voice, and LLM provider. The Settings page then adds
   Change Password and the onboarding checklist on top. Choosing a bot tone and
   choosing an LLM model sit in the same view.
3. **The landing page does not sell.** [`app/page.tsx`](../../../dashboard/app/page.tsx)
   is four static sections with no product visual, no motion, and a six-item
   equal-card icon grid, which is the single most generic marketing layout there
   is. Meanwhile a finished 55-second promo video and a full logo set sit unused
   on disk.

## 2. What the brand kit actually specifies

Extracted from `Branding+Marketing/Qonvo Brand Kit.pdf` (single page, 1376 x
12188 pt, section 02 for color and section 03 for type).

| Token | Name | Hex | Role |
|---|---|---|---|
| primary | Signal Green | `#00C776` | Actions and highlights |
| ink | Ink | `#08130E` | Text, dark background |
| surface | Deep Forest | `#0B3B2B` | Dark surface |
| accent | Volt | `#C6FF3D` | Loudest CTA only, "a spotlight, not a background" |
| paper | Paper | `#F3EFE6` | Light background |

**Type.** Bricolage Grotesque for display at weights 700-800. Manrope for body
at weights 400-700. Both are on Google Fonts, so `next/font/google` covers them
with no self-hosting.

**Voice** (section 04). Bold, direct, warm, confident, clear. Sells outcomes,
not features. Approved examples: "It books the slot. You keep the customer.",
"Replies in seconds, not hours.", "Never miss a message again." Rejected
examples: "Leverage AI-powered conversational synergy.", "A revolutionary
chatbot solution.", "Please await our representative."

**Current versus specified:**

| Token | Specified | In code today |
|---|---|---|
| Signal Green | `#00C776` | `#00d26a` |
| Ink | `#08130E` | `#071410` |
| Deep Forest | `#0B3B2B` | `#163325` |
| Volt | `#C6FF3D` | `#c6f432` |
| Paper | `#F3EFE6` | `#f7f5f0` |
| Display font | Bricolage Grotesque | Geist |
| Body font | Manrope | Geist |

## 3. Design read and dials

**Design read:** SMB SaaS landing for non-technical business owners, with a bold
high-contrast product-brand language already fixed by an existing kit, leaning
toward Tailwind v4 plus Bricolage Grotesque / Manrope plus Motion.

Two rulebooks apply, because the `design-taste-frontend` skill explicitly
excludes dashboards and dense product UI:

| Surface | Rulebook | VARIANCE | MOTION | DENSITY |
|---|---|---|---|---|
| Landing, auth, legal | `design-taste-frontend` | 7 | 7 | 4 |
| Dashboard | `redesign-existing-projects` audit plus IA requirements | 3 | 3 | 5 |

The existing site reads as roughly `2 / 1 / 4`, so the marketing surface is a
redesign-overhaul and the dashboard is an IA fix with restrained polish. Both
surfaces share one token layer.

## 4. Decisions taken

- **Icons stay `lucide-react`.** Both skills discourage Lucide as a default and
  both allow it when the project already depends on it. Swapping 60+ call sites
  buys nothing.
- **Pricing ships with no numbers at all.** Pricing is not decided and the
  earlier placeholder figures were unrealistically high. The section stays, so
  visitors understand this is a paid product with a free trial, but it carries
  no figures. See 7.3.
- **CRM sync is cut from the feature grid and answered in the FAQ.** It is
  planned, not shipped. A "coming soon" badge in the main feature bento
  advertises incompleteness at the moment the page is trying to convince, so it
  costs conversions. Saying nothing loses the buyer who needs CRM sync. The FAQ
  is where that buyer looks and is the right register for a roadmap answer.
- **Contact details live in one file.** `lib/contact.ts` holds the WhatsApp
  number and the email address. Nothing else references them, so moving to a
  domain address later is a one-file edit.
- **No social proof section.** There are no customers or quotes yet. Fabricating
  a testimonial is both an AI tell and a real trust problem. The section is
  omitted rather than faked. The brand kit's testimonial template with
  `[Owner Name]` placeholders stays unused until there is a real quote.
- **The domain is never hardcoded.** It may be `qonvo.ai` or `qonvo.org`. A
  single `NEXT_PUBLIC_SITE_URL` drives canonical URLs, OG tags, sitemap, and
  `llms.txt`.
- **Copy carries zero em dashes and zero en dashes used as separators.** This is
  stricter than the brand kit, which uses em dashes freely. Both loaded skills
  ban the character outright as the top AI tell, so the user rule and the skill
  rule agree against the kit. Only the plain hyphen is permitted.

## 5. Foundation

### 5.1 Tokens

Replace the five approximated hex values in the `@theme` block of
`app/globals.css` with the extracted values. The semantic layer below it
(`--background`, `--primary`, `--surface`, and so on) already reads from those
variables and nothing hardcodes a hex outside that block, so this is a
contained change that propagates everywhere.

Add a documented `--z-*` scale to replace ad-hoc z-index values, and a
`--shadow-*` scale using shadows tinted toward Ink rather than pure black.

Volt gets a usage rule enforced by convention: it appears on at most one
element per viewport, per the kit's "spotlight, not a background" instruction.

### 5.2 Type

Load Bricolage Grotesque and Manrope in `app/layout.tsx` via
`next/font/google`, replacing Geist. Keep Geist Mono, bound to numeric and
tabular contexts only.

Type scale, display in Bricolage with tight tracking, body in Manrope capped at
65 characters:

| Role | Size | Weight | Tracking |
|---|---|---|---|
| Hero | `text-5xl` to `text-7xl` | 800 | `-0.03em` |
| Section | `text-3xl` to `text-4xl` | 700 | `-0.02em` |
| Card title | `text-lg` | 700 | `-0.01em` |
| Body | `text-base` | 400 | normal |
| Label | `text-sm` | 500 | normal |

Introduce weights 500 and 600, which the current build never uses, so hierarchy
stops relying on the 400/700 jump alone.

### 5.3 Brand assets

`dashboard/public/` currently holds only `.gitkeep`. There is no favicon and no
logo file. [`components/logo.tsx`](../../../dashboard/components/logo.tsx) draws
a CSS circle containing the letter "Q", which is not the brand mark. The real
mark is a speech bubble holding a voice waveform.

Populate `public/` from `Branding+Marketing/`:

| Output | Source | Purpose |
|---|---|---|
| `logo-mark.png` (512, 1024) | `logo/qonvo-logo-512.png`, `-1024.png` | App and marketing mark |
| `logo-mark-ink.png` | `logo/qonvo-logo-512-ink.png` | Light-background mono |
| `favicon.ico`, `icon.png`, `apple-icon.png` | `logo/qonvo-logo-512.png` | Tab and home-screen icon |
| `og-default.png` (1200 x 630) | Composed from mark plus Ink background | Social cards |
| `hero.mp4`, `hero.webm` | Promo video, trimmed and compressed | Hero loop |
| `hero-poster.jpg` | Promo video frame near t=34s | Video poster, LCP element |
| `conversation.png` | Promo video frame near t=36s | The booking-flow still |

Rewrite `Logo` to render the real mark, switching between the standard and ink
variants by theme.

### 5.4 Hero video pipeline

The promo video is 1920x1080, 30fps, 55s, 9.1MB, and has **no audio stream**,
which makes it safe to autoplay muted and loop.

Two edits are required before it ships:

1. **Trim the closing card.** The final seconds display `qonvo.ai`. The domain
   is not settled, so the loop ends on "Never miss a customer again." instead.
2. **Cut to a hero-length loop.** 55s is far too long for a hero. Use the
   segment covering the message arriving through the booking confirmation,
   roughly t=24s to t=40s, which is the part that demonstrates the product.

Encode at 1280px wide, H.264 for `hero.mp4` and VP9 for `hero.webm`, targeting
under 1.5MB each. `preload="metadata"`, `playsInline`, `muted`, `loop`, with
`hero-poster.jpg` as the poster so LCP resolves on the image rather than the
video. Under `prefers-reduced-motion: reduce` the video does not play and the
poster is shown as a static image.

### 5.5 Dependency

`motion` is not currently installed. Add it:

```
npm install motion
```

Import from `motion/react`. Every component using it is a `'use client'` leaf.
No GSAP, no Three.js, so nothing competes for frames.

## 6. Dashboard information architecture

**Organising principle: the business and its bot live in the sidebar. The person
lives under the avatar menu.** That single split resolves the profile bundling
and separation-of-concerns requirements.

### 6.1 Navigation

Today the sidebar is a flat list of seven items with no grouping, and there is
no account area anywhere, which is why Change Password ended up inside
Settings.

New sidebar, grouped with section labels:

| Group | Items |
|---|---|
| *(ungrouped)* | Inbox, Analytics |
| AI rep | Knowledge, Behavior, Skills |
| Setup | WhatsApp, Integrations |
| Workspace | Business, Team, Billing |

New avatar menu in the topbar: Profile, Password, Preferences, theme toggle,
Sign out.

The `qonvo_admin` role keeps its existing separate admin nav unchanged. An admin
has no tenant, so owner pages 403 for them, and that logic in
[`components/sidebar.tsx`](../../../dashboard/components/sidebar.tsx) stays as
is.

### 6.2 Where today's Settings fields land

| Field today | New home |
|---|---|
| Business name | Workspace → Business |
| Persona, tone, primary language, custom instructions | AI rep → Behavior |
| Business hours, enforce-hours toggle, after-hours reply | AI rep → Behavior |
| Voice reply mode | AI rep → Behavior |
| Payment details | AI rep → Skills |
| Owner alert number, notify-on-handoff | AI rep → Skills |
| LLM provider, LLM model | Workspace → Business, "Advanced" disclosure |
| Change password | Account menu → Password |
| Onboarding checklist | Inbox, as a dismissible first-run card |

Rationale for the two least obvious moves. **Voice reply mode** is behavior, not
engine config: it decides whether customers hear a voice back. The provider and
model are engine config and belong behind an Advanced disclosure, far from
persona, because a tenant owner should never need them. **Escalation** moves
next to Skills because handoff is a thing the bot does, and it pairs with the
`human_handoff` skill it drives.

### 6.3 Component consequences

`tenant-config-form.tsx` is 385 lines covering six concerns and gets split into
one form per destination page, each owning its own fields and its own save.
Field `name` attributes and the config API payload keys stay identical, so no
backend change and no analytics breakage.

`ChangePasswordCard` moves under the account route unchanged.

### 6.4 Dashboard polish

Applied from the redesign audit, at `MOTION 3`, so nothing decorative:

- Skeleton loaders already exist and match layout shape. Keep them.
- Add empty states to Inbox, Knowledge, and Analytics. There is an
  `ui/empty-state.tsx` primitive already, currently underused.
- Add `:active` press feedback (`scale-[0.98]`) and visible focus rings to
  every interactive element.
- Active nav state stays, restyled to the corrected tokens.
- Tabular numerals on every metric in Analytics.

## 7. Landing page

Ten sections, ten distinct layout families. Constraint budget: at most 4
eyebrows for 10 sections and the design uses 2, at most 1 marquee and the design
uses 1, and no three consecutive split layouts.

| # | Section | Layout family | Motion |
|---|---|---|---|
| 1 | Hero | Asymmetric split | Video loop, staggered copy entry |
| 2 | The 2 AM problem | Full-bleed dark statement | Scroll reveal on the cost list |
| 3 | The same message, answered | Split, mirrored from hero | Conversation still, scroll reveal |
| 4 | What it does | Bento, 4 cells of varied size | Staggered cell reveal |
| 5 | Voice | Full-width dark media | Waveform on play |
| 6 | Languages | Kinetic marquee | Continuous, the page's only marquee |
| 7 | How it works | Sticky-stack, 3 steps | Pin and scrub |
| 8 | Pricing | Single card, no tiers | Hover elevation only |
| 9 | FAQ | Two-column list | None |
| 10 | Closing CTA plus footer | Centered statement | CTA hover |

### 7.1 Hero

Four text elements maximum, which is the cap. No eyebrow, no trust strip, no
tagline under the CTAs.

- **Headline:** "Never miss a customer again." Two lines at desktop. This is the
  brand's own closing line from the promo video and it already appears as the
  sidebar footer string.
- **Subtext, 19 words:** "Qonvo answers on your WhatsApp number in seconds, day
  or night, then books the slot and logs the lead."
- **CTAs:** "Start free trial" primary, "Sign in" secondary. One label per
  intent across the whole page.
- **Visual:** the trimmed hero video, right column.

Top padding capped at `pt-24`. Headline scale `text-5xl md:text-6xl lg:text-7xl`
given the short headline.

### 7.2 Section 4 and the CRM claim

Section 4 lists what Qonvo does. The promo video's equivalent frame reads "Logs
the lead to your CRM", which is **not supported yet**: per `CLAUDE.md`, CRM sync
is remaining Phase 3 work and leads go to a Google Sheet. It is planned, so the
claim is premature rather than untrue.

The feature grid says "Logs every lead to a Google Sheet you control" and makes
no CRM claim. This is not a downgrade to hide behind: for many small businesses
a Google Sheet is the CRM, so the copy states the capability plainly rather than
apologetically.

The roadmap answer lives in the FAQ, per 7.4. The hero loop is cut to the
booking segment, which avoids the CRM frame entirely, and the video itself needs
a re-render before that frame can be shown standalone anywhere, including the
brand kit's social posts.

### 7.3 Pricing

Prices are not decided, so the section carries none. It exists to answer one
question, "is this paid?", and to route buyers who want a number to a human.

A single card, not a three-tier comparison. Three tiers with no figures reads as
broken, and the three-tower pricing table is a flagged generic pattern
regardless.

Contents:

- Headline establishing that it is paid and starts free.
- A plain list of what a subscription includes, drawn from shipped features
  only, so no CRM and no team seats until those land.
- The trial stated as 14 days, no card required. The 300-message cap is not
  shown here, it is answered in the FAQ, per 7.4.
- Primary CTA "Start free trial", matching the hero label exactly, since one
  label per intent applies across the page.
- Secondary "Contact us for pricing", a distinct intent from signup and
  therefore not a duplicate CTA.

When prices are settled this card expands into tiers in place, without the
section moving or the surrounding rhythm changing.

**Contact targets.** Both resolve from `lib/contact.ts`:

| Channel | Value | Treatment |
|---|---|---|
| WhatsApp | `+92 319 4505305` | Primary, a `wa.me` link with a prefilled message |
| Email | `alihuzezzy@gmail.com` | Secondary, a quieter `mailto:` text link below |

WhatsApp leads because a product selling a WhatsApp AI rep should be reachable
on WhatsApp.

**The WhatsApp number is answered by Qonvo itself, deliberately.** The number
runs the product, configured with Qonvo's own knowledge base so it answers
questions about the system and points people to the trial. That makes the
contact button a live demo rather than a support channel, and the copy should
say so instead of hiding it. Suggested treatment, to be finalised during the
landing build:

> **Message us on WhatsApp.** You will be talking to Qonvo. That is the point.

Email remains the human-answered fallback for anyone who wants one, which is
the second reason to keep both channels.

One caveat still stands: both values are personal rather than company-owned and
will be scraped once public, which is why they are isolated in one file.

### 7.4 FAQ

Eight questions in a two-column list rather than an accordion, since the
redesign audit flags accordion FAQs as a generic pattern and flat text is what
LLM crawlers can actually read. Content is answer-shaped for citation: each
answer opens with a direct one-sentence response before elaborating. This
section is the source for FAQPage structured data.

Ten questions, covering: whether it uses your own WhatsApp number, whether a
customer can tell it is AI, what happens when it does not know something, how
handoff works, which languages it handles, whether it can book into an existing
calendar, what happens to your data, how long setup takes, plus the two below
which carry information deliberately kept off the rest of the page.

**CRM**, per 7.2:

> **Does Qonvo sync to my CRM?**
> Not yet. Today Qonvo logs every lead to a Google Sheet you control, which you
> can import or connect to most CRMs. Direct sync is on the roadmap.

**Trial cap.** The hero and pricing section state 14 days free, no card
required, and both are true. The 300-message cap from `TRIAL_MESSAGE_QUOTA` in
`backend/app/services/auth.py` is disclosed here rather than in the headline, so
it stays discoverable without complicating the top of the page:

> **What are the limits during the free trial?**
> The trial runs 14 days or 300 customer messages, whichever comes first. No
> card required to start.

## 8. Copy

Every visible string is rewritten and audited. Rules, in force order:

1. Zero em dashes and zero en-dash separators. Plain hyphen only.
2. Outcome-led, matching the kit's voice pills: bold, direct, warm, confident,
   clear.
3. Sentence case for headers, not Title Case.
4. No filler verbs. Banned: elevate, seamless, unleash, next-gen, revolutionize,
   effortless, supercharge, delve, transform.
5. No exclamation marks in success messages. No "Oops" in errors.
6. Active voice. "We could not save your changes", not "changes were not saved".
7. Claims must be true. No CRM claim until CRM sync ships. "Live in a day. No
   code." replaces "Live in about five minutes", matching the video.

Scope includes the landing page, auth pages, empty states, error messages,
button labels, and the onboarding flow. Alt text is written for every image.

## 9. SEO and AIO

All URLs derive from `NEXT_PUBLIC_SITE_URL`. Nothing hardcodes a domain.

**Metadata.** Per-page `title` and `description` via the App Router `metadata`
export. OG and Twitter card tags on every public route. `og-default.png` at
1200 x 630 as the fallback image.

**Crawl.** `app/robots.ts` and `app/sitemap.ts` generating from the public route
list. Dashboard routes are excluded, and `middleware.ts` already gates them.

**Structured data.** JSON-LD injected server-side:

- `SoftwareApplication` on the landing page, with `applicationCategory` set to
  BusinessApplication. **No `offers` block**, because prices are undecided and
  emitting a fabricated or zero price is worse than emitting none. When pricing
  is settled, `offers` is added at the same time as the visible tiers.
- `Organization` in the root layout.
- `FAQPage` on the landing page, generated from the same array that renders the
  FAQ section, so markup and visible text can never drift.

**AIO.** A `public/llms.txt` describing what Qonvo is, who it is for, what it
does, and what it does not do, following the emerging convention. The FAQ
answers are the citation surface, which is why they are flat text rather than
JavaScript-gated accordions.

## 10. Testing

The dashboard has no test suite today, so this adds no automated coverage and
relies on the checks the repo already uses plus explicit manual verification.

**Automated:**

- `npm run build` must pass with no type errors.
- `npm run lint` must pass.
- Backend suite must stay green at 211 passing and 6 skipped, confirming no API
  contract drifted. No backend file is touched, so this is a regression guard.

**Manual, per the deploy notes in `CLAUDE.md`:**

- Rebuild and restart the dashboard using the committed script, since
  `next start` does nothing under `output: "standalone"`.
- `rm -rf .next/standalone/.next/static .next/standalone/public` before copying,
  or stale chunks cause `ChunkLoadError`.
- Hard refresh with Ctrl+Shift+R after each restart, since chunk hashes change.
- Verify every migrated Settings field still saves, reading back from the API.
- Verify both light and dark themes on every changed page.
- Verify at 375px, 768px, and 1440px.
- Verify with `prefers-reduced-motion: reduce` set, confirming the hero video
  holds on its poster and no scroll animation runs.
- Run Lighthouse on the landing page, targeting LCP under 2.5s, INP under
  200ms, CLS under 0.1.

**Pre-ship grep gates:**

- No `—` or `–` in any file under `dashboard/app/` or `dashboard/components/`.
- No hardcoded `qonvo.ai` or `qonvo.org` outside `.env` files.
- No hex color literal in any component file. All color flows from tokens.
- No phone number or email address outside `lib/contact.ts`.
- No currency symbol or price figure anywhere in `dashboard/app/`, guarding
  against a placeholder price reappearing.

## 11. Sequencing

Foundation first so both surfaces inherit it and nothing gets built twice.

1. **Foundation.** Tokens, fonts, `public/` assets, `Logo` rewrite, video
   pipeline, `motion` install.
2. **Landing.** Ten sections, then metadata, structured data, `robots`,
   `sitemap`, `llms.txt`.
3. **Dashboard.** Nav grouping, avatar menu, account routes, `tenant-config-form`
   split, empty states, polish.
4. **Copy sweep.** Full audit across every surface, then the grep gates.

Each stage ends green on build and lint before the next begins.

## 12. Out of scope

- Backend, API, and database. Nothing outside `dashboard/` changes.
- The admin console at `/admin/*` inherits tokens and fonts but keeps its
  current IA.
- Re-rendering the promo video to fix the CRM claim and the baked-in domain.
  Flagged, not done here.
- Real pricing, real testimonials, the final domain, and a company-owned
  contact address. Each is a single-file change once decided, landing in
  `lib/pricing.ts`, the FAQ array, `NEXT_PUBLIC_SITE_URL`, and `lib/contact.ts`
  respectively.
- CRM sync itself, which remains Phase 3 work.
