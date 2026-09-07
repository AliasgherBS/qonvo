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
| **CSP allows `'unsafe-inline'` scripts** | Next's hydration bootstrap and the pre-paint theme script. Fix is per-request nonces threaded through the document. |
| **No rate limiting on authentication** | `/api/auth/login` and the password-reset request accept unlimited attempts. Argon2 makes each guess expensive, and the reset endpoint does not reveal whether an address exists, so this is throttling rather than a hole. Should be closed before any real traffic. |
| **Load testing never run** | The one row in the E2E plan still marked "never". Not a vulnerability, but an unmeasured failure mode. |
| **Backups are local-only** | Postgres and the WAHA session files exist only on the box being backed up. |

---

_Method: git history scanned for secret shapes and for the exact live values;
committed `.env` diffed against the current one to separate rotated from
still-live; every datastore's port bindings checked for public exposure;
response headers read from both live hosts; the WAHA HMAC path traced from
config to verification before judging it._
