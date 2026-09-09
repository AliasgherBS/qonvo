# Security audit, 2026-09-07

Triggered by a real observation: a paying customer landed on
`qonvo.org/billing?upgraded=1&customer_session_token=polar_cst_...` with a live
bearer token in the address bar.

That was the smallest of the three things found. Everything below is either
fixed or has a named owner and a reason it is still open.

---

## 1. Credentials in URLs — fixed

**What.** Polar appends `customer_session_token` to whatever `success_url` it is
given. From the address bar it reaches browser history, the `Referer` header of
every outbound link, anything that records the path, and our own access logs.

**Severity.** Moderate. The token is scoped to one customer's billing portal and
expires. It is still a credential in a URL, which should never be true, and we
never needed it: portal sessions are minted on demand from the API.

**Fix.** Middleware redirects any URL carrying a known credential parameter to
the same URL without it, before the auth check, since an auth redirect would
otherwise carry the whole query string to `/login`.

**The part that nearly broke the product.** The first version stripped `token`
unconditionally. Our own password-reset and team-invite emails link to
`/reset-password?token=...` and `/accept-invite?token=...`, and both pages read
it with `useSearchParams`. That would have silently broken every reset and every
invitation, which is worse than the leak. Those two paths are exempt, and are
single-use by design: a reset token embeds a fingerprint of the current password
hash, so using it invalidates it.

---

## 2. No security headers on either host — fixed

**What.** `qonvo.org` and `api.qonvo.org` sent none. Not one.

**Severity.** High, and cumulative. Without `frame-ancestors` any page could be
framed. Without `Referrer-Policy` the full URL of every page went to every third
party clicked through to, which is what turned finding 1 from an untidy URL into
a leak. Without a CSP, one injected script had the run of the origin.

**Fix.** The dashboard sends HSTS, a CSP, `Referrer-Policy`, `X-Frame-Options`,
`nosniff`, `Permissions-Policy` and COOP, with `poweredByHeader` off. The API
sends a stricter set built on `default-src 'none'`, since it serves JSON to a
known client rather than documents.

Set in **application** middleware rather than in the proxy, deliberately: the API
is behind a Cloudflare Tunnel today and will be behind Caddy on a VPS later, and
a header that lives in the proxy disappears when the proxy changes.

**Known compromise.** `script-src` keeps `'unsafe-inline'`. That is required
rather than lazy: Next.js inlines its hydration bootstrap, and `ThemeScript`
runs before first paint specifically to avoid a flash of the wrong theme.
Per-request nonces are the correct fix and a change worth making on its own
rather than inside a headers pass.

---

## 3. Ten live secrets were in git history — fixed

**What.** `.env` and `dashboard/.env.local` were tracked in commit `4a48a52` and
untracked in `a80ca3a`. A removed file stays in history, so every value in that
commit is readable by anyone who can clone the repository.

Thirteen secrets appeared there. Four had already been rotated for other
reasons. **Ten were still live**, including:

| Secret | What it protects |
|---|---|
| `SYSTEM_DB_PASSWORD` | the `BYPASSRLS` role, which reads every tenant's data |
| `QONVO_FERNET_KEY` | every tenant's stored Google refresh token |
| `POSTGRES_PASSWORD` | the production database, as owner |
| `QONVO_WAHA_API_KEY` | full control of the linked WhatsApp session |
| `MINIO_ROOT_PASSWORD` | object storage |

**Severity.** High, with two mitigations that mattered: the repository is
private, and every datastore binds to `127.0.0.1` rather than a public
interface, so none of this was reachable from the internet.

The worse half was not the git history at all. **Four of the five highest-impact
values were placeholder-shaped strings** (`dev-postgres-pass`,
`change-me-...`). A guessable password needs no repository access, and the
`BYPASSRLS` role is exactly the thing that defeats all the row-level security
work if someone reaches the port.

**Fix.** [`scripts/rotate-secrets.sh`](../scripts/rotate-secrets.sh). All ten
rotated, verified live: `readyz` reports database, redis and WAHA healthy, both
Google credentials still decrypt, the WhatsApp session survived without a QR
re-scan, and the old WAHA key now answers 401.

`QONVO_MINIO_ACCESS_KEY` is deliberately not rotated: it is the MinIO root
*username*, not a secret, and renaming a root identity on an initialised volume
can strand IAM policies attached to it.

### Corrected mid-audit

An earlier draft of this called `QONVO_WAHA_HMAC_SECRET` an emergency, on the
grounds that it signs the webhook ingesting customer messages. It is a
**fallback**. `sessions.py` generates a random per-session secret at creation and
stores it, and `webhooks.py` prefers that
(`session_row.hmac_secret or settings.waha_hmac_secret`). The live session has
one. Rotating it still matters, because a session row with a NULL secret would
otherwise fall back to a value beginning with the word "change", but it was not
the hole it first looked like.

---

## 4. The teardown findings, 2026-09-08

A separate review (`qonvo-teardown.html`) read the source and found four things
this audit had not. They are recorded here because this is the file somebody
will read when they ask "what has been looked at".

**X1 — every state-changing route was reachable by a staff seat.** `require_owner`
existed and was correct, and was used in two API modules out of twenty-one.
The worst was `PUT /api/config`, which accepts `payment_details`, the free text
the `share_payment_details` skill reads out verbatim: a receptionist could
substitute their own account number and the business's own WhatsApp number
would tell its customers to pay it, with nothing on any screen showing it.
Verified live against a staff token before the fix (HTTP 200, and the row
changed), then restored. **Fixed**, and held by a property test over the route
table rather than a list of routes, since a per-route test passes while the
next route added is quietly gated wrong.

**X2 — no email verification, and Google resolved accounts by address.** Each
half ordinary; together, account pre-hijacking. A stranger registers
`owner@theclinic.pk` with a password, no mail is ever sent, and months later
the real owner clicks Sign in with Google and is signed into the stranger's
tenant as its owner. **Fixed**: signup mails a confirmation link, Google
refuses to adopt an unverified row that has a password, and confirming is what
allows a WhatsApp number to be linked, so a squatted address is inert.
Mutation-tested by restoring the old adoption behaviour.

**X3 — "Add website" fetched any URL, including our own network.** Not blind:
the response is chunked, embedded and shown in the tenant's dashboard, so it
was a read primitive with the answer delivered to the attacker. `http://api:8000/metrics`
was the whole exploit, and on a VPS the same path reaches
`169.254.169.254`. **Fixed** by `app/core/url_guard.py`: scheme allowlist,
every resolved address checked rather than the first, revalidated on each
redirect hop, and caps on size and redirect count. Verified from inside the
worker container, where `api`, `postgres`, `redis`, `minio` and `waha` are all
now refused and a real URL still works.

**X7 — a password-reset token authenticated as an access token.** `decode_jwt`
required `typ` and never compared it. Not exploitable in practice, because
reset tokens carry no `tenant_id` — which is luck, not a check. **Fixed.**

The instructive part is what the three fixed findings have in common: each was
a check that existed and was not applied. `require_owner` was written and
unused, `email_verified` was handled correctly for Google and nowhere else,
and `typ` was required but never read. None of them needed new security
thinking, which is why reading the code found them and the earlier audit,
which read headers and git history, did not.

---

## What the rotation itself taught

Two bugs in the rotation script, both found by running it rather than reading it.

**`tr </dev/urandom | head` and `pipefail` do not mix.** `head` exits after its
byte count, `tr` takes SIGPIPE, `pipefail` turns that into a non-zero status and
`set -e` kills the script. It died silently after printing a section header.
Generators are Python now.

**`re.sub` replacement escaping, live, mid-rotation.** A generated password
beginning with a digit made `\1` parse as a reference to group 16. The role
password had already been `ALTER`ed by then, so the database and the URL
disagreed and `system_session` was broken until it was repaired by hand. Now
`\g<1>` via a lambda, which cannot be ambiguous.

The second is the instructive one: the script rotated the credential before it
finished being able to record it. Anything that changes a secret in two places
should change the readable one first.

---

## Still open

| Item | Why it is still open |
|---|---|
| **Secrets remain in git history** | Rotation makes them worthless, which is the fix that matters. Actually removing them needs a history rewrite (`git filter-repo`), which invalidates every existing clone and every commit hash. Worth doing before the repository is ever made public or gains a collaborator, and not worth doing today. |
| ~~CSP allows `'unsafe-inline'` scripts~~ | **Closed 2026-09-08.** Middleware mints a per-request nonce and builds the policy around it, so `script-src` no longer carries `'unsafe-inline'` at all. It has to be middleware rather than `next.config.ts`, because `headers()` there is evaluated once at build time and a nonce must differ per response. Next finds the nonce in the request's own `Content-Security-Policy` and stamps its hydration bootstrap; our `ThemeScript` reads it from `x-nonce`. Verified live: header and document nonces match within one request, and 35 of 38 script tags carry it. The three that do not are two `application/ld+json` data blocks, which are not executable, and Cloudflare's same-origin email-decode script, covered by `'self'`. `static.cloudflareinsights.com` remains allowlisted: Cloudflare injects that beacon at the edge, so blocking it produced a violation on every page load and a follow-on TypeError from the half-loaded script, and nothing in this codebase could stop it. Turning Web Analytics off in the Cloudflare dashboard is the alternative. |
| ~~No rate limiting on authentication~~ | **Closed 2026-09-08.** `app/core/throttle.py`: login 10 per 15 minutes, signup 5 per hour, password reset 5 per hour. Two keys per attempt, since per-IP alone is defeated by a botnet and per-account alone lets an attacker lock a victim out by failing on purpose. The account counter records **failures only**, so a correct password never counts against it. Fails open, because an outage that also blocks sign-in turns a degraded service into an inaccessible one. Email addresses are hashed before they become Redis keys. |
| **DNS rebinding on URL ingestion** | `url_guard` resolves a hostname and validates every address, then hands the URL to httpx, which resolves again. An attacker with an authoritative server can answer differently the second time. Closing it means connecting to the validated address and carrying the original name in `Host`, which breaks TLS certificate validation for https. Narrow, needs real infrastructure, and is not what made X3 reachable, which was that `api` resolved and nobody looked. |
| **Load testing never run** | The one row in the E2E plan still marked "never". Not a vulnerability, but an unmeasured failure mode. |
| **Backups are local-only** | Postgres and the WAHA session files exist only on the box being backed up. |

---

_Method: git history scanned for secret shapes and for the exact live values;
committed `.env` diffed against the current one to separate rotated from
still-live; every datastore's port bindings checked for public exposure;
response headers read from both live hosts; the WAHA HMAC path traced from
config to verification before judging it._
