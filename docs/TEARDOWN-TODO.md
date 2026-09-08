# Teardown remediation — full inventory

Every finding in `qonvo-teardown.html` (reviewed against the live site, 8 September
2026), in the order it will be worked rather than the order it was reported.

**64 findings. 3 are commendations** (V8, S6, D3) and need nothing. **61 actionable.**

**Phases 2 to 9 are being worked in parallel** by six streams with disjoint file
ownership. `dashboard/lib/api.ts` is shared, so `apiFetch` is exported from it
and each stream owns a `dashboard/lib/api/<domain>.ts` instead; no stream writes
an alembic migration, so the revision chain stays linear and one combined
migration is written centrally.

Ordering is by dependency, not by severity. Anything that moves a field between
pages (V2) has to land before the per-page polish for those pages (V4–V7, P1,
P2, B2–B4), or the polish is done twice. Anything that changes a shared
primitive (dates, the rep switch, the nav groups) lands before its consumers.

**Deferred** means it needs the owner's decision, an asset only they can supply,
or an enrolment only they can perform — not that it is hard. Those are collected
in the last table and are deliberately not started.

---

## Phase 0 — done

| ID | Sev | Finding | Commit |
|---|---|---|---|
| X1 | Critical | Staff seat could cancel billing, change plan, rewrite `payment_details` | `092bb85` |
| X7 | Latent | Reset token satisfied `decode_jwt` — `typ` required but never compared | `092bb85` |
| V3 | Broken | Sidebar showed staff every owner-only page | `4efe591` |
| X2 | Critical | No email verification + Google matched on email → pre-hijacking | `4efe591` |
| X3 | High | `fetch_url_text` would fetch our own Docker network | `5a947ee` |
| B1 | Broken | Business hours evaluated in UTC, unchangeable | `afd53fe` |
| N1 | Broken | Calendar timezone also UTC — bookings five hours off | `afd53fe` |
| Y1 | Broken | The only chart in the product painted nothing | `b89ee20` |
| S1 | Broken | Mobile bar in normal flow, at the end of the document | `b89ee20` |
| S2 | Broken | Five pages unreachable on a phone | `b89ee20` |
| — | — | Product tour ringed 0,0 on mobile (not in the report) | `2c329e7` |

V2 is partly done: the timezone was rehomed to Business. The rest of the
scattering is Phase 4.

---

## Phase 1 — security, no UI dependencies

Independent of every UI change, so it goes first and cannot be invalidated by
the rehoming that follows.

| # | ID | Sev | What |
|---|---|---|---|
| ~~1~~ | ~~X8~~ | Medium | **Done.** Audit rows for every state-changing owner route, actor resolved and named. Held by a property test over the route table |
| ~~2~~ | ~~X6~~ | Medium | **Done.** `jti` + denylist for one session, per-subject and per-tenant markers for bulk. Wired to sign-out, sign-out-everywhere, password change, password reset, member removal and suspension. Auth.js session aligned to 24h |
| ~~3~~ | ~~X5~~ | Medium | **Done.** Minimum 12, no composition rules, HIBP k-anonymity screening, business name and email local part refused, strength meter on all four forms |
| ~~4~~ | ~~X9~~ | Low | **Done.** Argon2id cost pinned to what was in use, `aud`/`iss` minted and required, disposable domains refused. Its fourth item (QR reachable by staff) was closed by X1 |
| ~~5~~ | ~~X6b~~ | Medium | **Done.** Rotating refresh keyed on a session id, capped at 14 days from the original sign-in; sign-out ends the session rather than one token |
| ~~6~~ | ~~X4~~ | High | **Built.** TOTP (RFC 6238, verified against the RFC vectors), replay protection, `act` claim on impersonated tokens, audited actions attributed to the real admin. **Enrolment is the owner's to do** — see the deferred table |

**Phase 1 is complete.** Every security finding in the teardown is closed, bar
one enrolment that is not code (see the deferred table).

## Phase 2 — shared primitives and factual corrections

Small, and they unblock or de-duplicate later work.

| # | ID | Sev | What |
|---|---|---|---|
| 6 | L2 | Costly | "Unlimited knowledge about your business" contradicts the caps that shipped. A false claim on a public page — corrected first, before anything cosmetic |
| ~~7~~ | ~~K4~~ | Polish | **Done.** `dashboard/lib/format.ts` — `formatDate`, `formatDateTime`, `formatRelative`, `formatTime`, all pinned to en-GB so a date reads the same to the owner and to us |
| 8 | A1 | Rough | Any unknown URL becomes a login page, or a bare browser 404. A real `not-found` page |

## Phase 3 — inbox

The largest change in how the product feels, per the report, and self-contained.

| # | ID | Sev | What |
|---|---|---|---|
| 9 | I1 | Costly | Customers shown as `923009998877@c.us`. Push name where present, formatted number otherwise |
| 10 | I2 | Broken | Composer starts below the fold at 1440×900; the whole page scrolls to reach it |
| 11 | I3 | Broken | On a phone, tapping a conversation appears to do nothing — panes stack |
| 12 | I4 | Rough | No search, no unread state, no dates. Breaks at 300 conversations |
| 13 | I5 | Polish | Redundant "Customer"/"Bot" labels, Urdu line height, transcript density |
| 14 | S4 | Rough | Notifications: no unread badge, no link through, and it quotes the model's reasoning at the owner |

## Phase 4 — information architecture

Must precede the per-page work below it: these move fields between pages.

| # | ID | Sev | What |
|---|---|---|---|
| 15 | V1 | Costly | "Setup" is a lifecycle stage as a category. Rename the group to Connections |
| 16 | V2 | Costly | Business facts live on four pages and Business holds none. Rehome name, country, contact number, opening hours onto Business |
| 17 | P2 | Rough | Business is a nav entry for one text field — resolved by V2 |
| 18 | V4 | Rough | Skills mixes three concerns and contains no skills. Move alert number and payment details out |
| 19 | P1 | Rough | The Skills page lists no skills. List the eight, with their gating |
| 20 | V5 | Rough | Profile says "how you appear to your team" and lets you set nothing |
| 21 | V7 | Rough | Read-only values dressed as form fields; "contact support" with no address |
| 22 | V6 | Rough | Account is missing 2FA, active sessions, "sign out everywhere", data export |
| 23 | B2 | Rough | Hours master switch says Off while all seven day rows look active |
| 24 | B3 | Rough | 2,000-character field in a five-line box; one Save for three cards |
| 25 | B4 | Polish | Seven identical day rows, no "apply to weekdays"; 745px form in a 1,150px area |
| 26 | S3 | Rough | The rep switch taxes every page by 90–130px. Move it into the top bar |
| 27 | S5 | Polish | Three dead spots: the setup-checklist item, and two others |

## Phase 5 — WhatsApp and integrations

Depends on V1 (the group rename changes what this page is for).

| # | ID | Sev | What |
|---|---|---|---|
| 28 | W1 | Broken | A connected tenant sees the same empty connect form as a new one. Make it a status page: number, state, last event, restart, re-link |
| 29 | W2 | Rough | Asks a salon owner to invent a "session name" |
| 30 | N2 | Rough | Reconnect is the primary button on a working connection |
| 31 | N3 | Rough | Nothing proves the integration has ever been used. "Last booking 2 hours ago" |

## Phase 6 — knowledge

| # | ID | Sev | What |
|---|---|---|---|
| 32 | K3 | Rough | The caps are metered and invisible on the page they govern |
| 33 | K2 | Rough | A source is a name, a type and a date. No contribution, no last-crawled |
| 34 | K1 | Rough | Gaps is the best idea in the product and a dead end. An "Answer this" button |

## Phase 7 — analytics

| # | ID | Sev | What |
|---|---|---|---|
| 35 | Y2 | Rough | Eight tiles of identical weight, five reading zero. Lead with two, add a range selector |

## Phase 8 — billing

| # | ID | Sev | What |
|---|---|---|---|
| 36 | Z4 | Costly | The card on file is never shown. Expiry is the largest preventable cause of involuntary churn |
| 37 | Z2 | Rough | Voice minutes are metered above and absent from the plan comparison |
| 38 | Z3 | Polish | Two dates that look like they disagree; empty meters that look broken |
| 39 | Z5 | Rough | Proration promised in prose, never shown as a number |
| 40 | Z6 | Rough | Nothing says what happens when a meter fills, and the consequences differ per meter |

## Phase 9 — landing page

| # | ID | Sev | What |
|---|---|---|---|
| 41 | L3 | Rough | A 7,600px page with no navigation. Pricing sits 5,133px down |
| 42 | L4 | Rough | Three consecutive sections leave the right half of a desktop viewport empty |
| 43 | L5 | Rough | The same conversation art twice, 1,600px apart |
| 44 | L6 | Polish | The language marquee repeats inside a single viewport |

---

## Deferred — needs the owner's decision, asset, or enrolment

Not started. Collected here so the reason is on the record.

| ID | Sev | What | What is needed |
|---|---|---|---|
| L1 / Z1 / D1 | Costly | Neither the site nor the plan picker names a price. The report notes three Polar products at **$10 / $18 / $30** | Confirmation that those are the public prices, and in which currency they are shown to a Pakistani buyer |
| Y3 | Rough | "AI cost $0.02" shows the customer our cost of goods | Whether owners should see this at all, or only staff/admin |
| Z7 | Polish | No billing email separate from the login address; no tax/VAT id field | Whether invoices need a separate recipient, and which tax fields apply |
| L7 | Polish | A page selling voice has no voice on it | A real voice sample. Generating one costs API credit |
| D2 | Not built | Three landing treatments shipped simpler than specified (sticky-stack, animating waveform, hero poster) | Design direction, and the poster frame to use |
| X4 (enrol) | High | TOTP on `qonvo_admin` | Enrolling an authenticator app |

---

## Not actionable — commendations

| ID | What |
|---|---|
| V8 | What the information architecture gets right |
| S6 | Things the reviewer went looking to criticise and could not |
| D3 | The September spec's hardest asks all shipped |
