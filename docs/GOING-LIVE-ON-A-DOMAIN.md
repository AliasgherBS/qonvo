# Going live on your own domain

_Everything that has to change, in the order it has to change, with the traps
that have already bitten this project marked._

Replace `qonvo.org` below with the domain you actually bought. It appears in
more places than you would expect, and **four of them are coupled** — change one
without the others and Google sign-in breaks with `redirect_uri_mismatch` from
every device.

---

## 0. Decide this first: where does it run?

A domain needs something to point at. Right now Qonvo runs on your machine
behind an ngrok tunnel, and this box's address (`58.65.198.91`) is a home
connection — almost certainly behind CGNAT, so **DNS cannot point at it
directly**. Two honest options:

| | **Path A — Cloudflare Tunnel** | **Path B — VPS** |
|---|---|---|
| Cost | **Free** | ~$7–12/month |
| Public IP needed | No | Yes |
| Runs on | This machine, as today | A rented server |
| TLS | Cloudflare terminates it | Caddy gets Let's Encrypt certs |
| Ready | **Today** | After the VPS move |

**Start on Path A.** It puts your real domain in front of the machine you are
already running, replaces ngrok, and costs nothing — so the domain stops being
blocked on a decision you deliberately deferred. Every config change below is
identical on both paths; only §2 differs. Moving to a VPS later changes where
DNS points, nothing else.

**Path B is still where this ends up.** A laptop is not a production host: it
sleeps, it reboots, and its uplink is not a datacentre. See
[DEPLOYMENT-AND-COSTS.md](DEPLOYMENT-AND-COSTS.md) for sizing and providers.

---

## 1. The shape of the domain

Two names, which is what the compose file and Caddyfile already assume:

| Host | Serves | Why |
|---|---|---|
| `qonvo.org` | The Next.js app: landing page **and** dashboard | The landing page is the marketing site, so it belongs on the apex where links and SEO point |
| `api.qonvo.org` | FastAPI | Separate origin, independently scalable, and the WhatsApp webhook has a stable home |
| `www.qonvo.org` | Redirect to the apex | So both spellings work and only one is canonical |
| `dev.qonvo.org` | Staging (optional) | Blocks already written in the Caddyfile, commented out |

**This is a change from today.** Behind the tunnel everything is one origin and
the dashboard proxies `/backend/*` to the API. On a real domain the API gets its
own hostname, which means CORS matters — §4 covers it.

---

## 2. DNS

### Path A — Cloudflare Tunnel

1. Add the domain to Cloudflare (free plan) and point your registrar's
   nameservers at the two Cloudflare gives you. Propagation is usually minutes,
   occasionally hours.
2. Install `cloudflared` and authenticate:
   ```bash
   cloudflared tunnel login
   cloudflared tunnel create qonvo
   ```
3. Map hostnames to the local services in `~/.cloudflared/config.yml`:
   ```yaml
   tunnel: qonvo
   credentials-file: /home/aliasgher/.cloudflared/<TUNNEL-ID>.json
   ingress:
     - hostname: qonvo.org
       service: http://localhost:3002      # the dashboard host process
     - hostname: api.qonvo.org
       service: http://localhost:8000      # the API
     - service: http_status:404
   ```
4. Create the DNS records — this writes the CNAMEs for you:
   ```bash
   cloudflared tunnel route dns qonvo qonvo.org
   cloudflared tunnel route dns qonvo api.qonvo.org
   ```
5. Run it, replacing the ngrok window in tmux:
   ```bash
   cloudflared tunnel run qonvo
   ```

**No ports are opened and no public IP is needed** — the tunnel dials outward.
That is also why it works from behind CGNAT.

### Path B — VPS

| Type | Name | Value | Proxy |
|---|---|---|---|
| A | `@` | your VPS IPv4 | off (Caddy needs to see the real request for ACME) |
| A | `api` | your VPS IPv4 | off |
| CNAME | `www` | `qonvo.org` | off |
| A | `dev` | your VPS IPv4 | off (only if you expose staging) |

Then open 80 and 443 on the VPS firewall. Caddy needs 80 reachable to get
certificates, not only 443.

---

## 3. Caddy (Path B only)

The [Caddyfile](../Caddyfile) already has `app.` and `api.` blocks. Change the
first to the apex and add the `www` redirect:

```caddy
qonvo.org {
	encode zstd gzip
	reverse_proxy dashboard:3000
}

www.qonvo.org {
	redir https://qonvo.org{uri} permanent
}

api.qonvo.org {
	encode zstd gzip
	reverse_proxy api:8000
}
```

Set `DOMAIN=qonvo.org` in `.env` — Caddy and the compose `dashboard` service
both read it.

**Leave the staging blocks commented until you actually want staging public.**
Caddy refuses to start if it cannot get a certificate for a host block, so an
unused one takes production down with it.

---

## 4. Application configuration

### `.env` (backend)

| Variable | Set to | Note |
|---|---|---|
| `DOMAIN` | `qonvo.org` | Caddy + compose only |
| `QONVO_DASHBOARD_BASE_URL` | `https://qonvo.org` | Where the OAuth callback sends the browser |
| `QONVO_GOOGLE_OAUTH_REDIRECT_BASE` | `https://api.qonvo.org` | **Drop the `/backend` suffix** — that existed only because the tunnel fronted the dashboard and proxied to the API. With `api.` on its own hostname there is no prefix. |
| `QONVO_CORS_ORIGINS` | `["https://qonvo.org","https://www.qonvo.org"]` | New requirement: the dashboard and API are now different origins |

### `dashboard/.env.local`

| Variable | Set to | Note |
|---|---|---|
| `AUTH_URL` | `https://qonvo.org` | **Must be explicit.** Auth.js host-derivation is unreliable behind a proxy — verified here: it honoured `X-Forwarded-Proto` but not the host, and built `https://localhost:3002/...` anyway |
| `NEXT_PUBLIC_API_URL` | `https://api.qonvo.org` | Was `/backend` |
| `NEXT_PUBLIC_SITE_URL` | `https://qonvo.org` | Feeds `metadataBase`, the sitemap, robots and OG tags. Wrong value = wrong canonical URLs everywhere |
| `INTERNAL_API_URL` | unchanged | Only used by the `/backend` rewrite, which is now unused |

> **`NEXT_PUBLIC_*` is baked in at build time.** Changing these needs
> `npm run build`, not a restart. A restart will silently keep serving the old
> values — this has cost time on this project before.

### Leave alone

`QONVO_WAHA_BASE_URL` and `QONVO_WEBHOOK_URL` are container-to-container
(`http://waha:3000`, `http://api:8000/webhooks/waha`). They are not public and
must not become public: the webhook is HMAC-signed but there is no reason to
expose it.

---

## 5. Google Cloud console

Both OAuth flows live on one client, so this is one place with two entries.

**APIs & Services → Credentials → your OAuth client:**

Authorised redirect URIs — add both, exactly:
```
https://api.qonvo.org/api/integrations/oauth/callback
https://qonvo.org/api/auth/callback/google
```

Authorised JavaScript origins:
```
https://qonvo.org
```

Note the asymmetry, because it has caused confusion here: the **integrations**
callback is on the API host, the **sign-in** callback is on the dashboard host.
They are different flows on the same client.

**OAuth consent screen:** update the app homepage, privacy policy and terms
links to `https://qonvo.org`, `https://qonvo.org/privacy`,
`https://qonvo.org/terms`.

**Check the publishing status is "In production".** A client left in Testing
issues refresh tokens that **expire after seven days**, so every tenant's Google
integration dies weekly. All scopes here are non-sensitive, so publishing is
free and needs no review.

**Keep the ngrok URIs until the switch is verified**, then delete them. Google
allows several; overlap costs nothing and is your rollback.

---

## 6. Email on the domain

Optional, but `hello@qonvo.org` reads better than a personal Gmail on a welcome
message, and deliverability is better.

> The full setup, including a **$0/month** receive-and-reply path with Cloudflare
> Email Routing, the address plan and the provider comparison, is in
> [`EMAIL-SETUP.md`](EMAIL-SETUP.md). What follows is the minimum.

Gmail SMTP can only send as an address it owns, so either use Google Workspace
(~$6/user/month) or a transactional provider. Whichever you choose, add these
or your mail lands in spam:

| Type | Name | Value |
|---|---|---|
| TXT | `@` | `v=spf1 include:<provider> ~all` |
| TXT | `<selector>._domainkey` | the DKIM key your provider gives you |
| TXT | `_dmarc` | `v=DMARC1; p=none; rua=mailto:you@qonvo.org` |

Start DMARC at `p=none` and only tighten to `quarantine` once the reports are
clean. Then set `QONVO_EMAIL_FROM=Qonvo <hello@qonvo.org>`.

**`docker compose up -d --force-recreate api worker scheduler` after changing
email vars** — env files are read at container *create*, so a plain restart
keeps the old values.

---

## 7. Order of operations

DNS first, because it is the slowest and everything else depends on it.

1. **DNS**, and wait for it to resolve: `dig +short qonvo.org`
2. **Tunnel or Caddy** up; confirm HTTPS works before touching app config
3. **Google console** — add the new URIs *alongside* the old ones
4. **`.env` and `dashboard/.env.local`**
5. **Rebuild the dashboard** (`NEXT_PUBLIC_*` is build-time) and recreate the
   backend containers
6. **Verify** (§8)
7. **Only then** remove the ngrok URIs from Google and stop the ngrok window

---

## 8. Verify

```bash
curl -sI https://qonvo.org | head -1              # 200, valid cert
curl -s https://api.qonvo.org/healthz             # {"status":"ok"}
curl -s https://api.qonvo.org/readyz              # db, redis, waha all ok
curl -sI https://www.qonvo.org | head -2          # 301 to the apex
```

Then by hand, in this order — each depends on the one before:

1. Load `https://qonvo.org` — landing page, no mixed-content warnings
2. Sign in with **email and password**. This proves `AUTH_URL` and CORS
3. Sign in with **Google**. This proves the redirect URI
4. Settings loads and saves. This proves `NEXT_PUBLIC_API_URL` and CORS on a
   write
5. **Integrations → Connect Google.** This proves the *other* redirect URI, the
   one on the API host
6. Send a WhatsApp message and get a reply. WAHA is internal, so this should be
   unaffected — if it broke, something changed that should not have
7. View source on the landing page: canonical and OG URLs say `qonvo.org`, not
   ngrok or localhost

---

## 9. If it goes wrong

Nothing here is destructive and every step is reversible.

| Symptom | Cause |
|---|---|
| `redirect_uri_mismatch` | The console URI does not match byte for byte. Check `https` vs `http`, trailing slash, and `api.` vs apex |
| Sign-in loops back to login | `AUTH_URL` wrong or unset, so the cookie lands on the wrong host |
| Dashboard loads, every API call fails | CORS. `QONVO_CORS_ORIGINS` must contain the exact origin |
| API calls still go to ngrok | The dashboard was restarted, not rebuilt. `NEXT_PUBLIC_*` is baked in |
| Caddy will not start | It could not get a certificate. Usually DNS has not propagated, port 80 is closed, or an uncommented host block has no DNS record |
| Google integration dies after a week | The OAuth client is still in Testing |

**Rollback:** put the ngrok values back in both env files, rebuild the
dashboard, restart. The old redirect URIs still being in Google is what makes
this a two-minute reversal — which is why §5 says to delete them last.

---

## 10. Afterwards

Done on 2026-09-06, when `qonvo.org` went live:

- ✅ **`CLAUDE.md` updated** — a "Public access" section describing the tunnel and
  the two hosts, the coupled-URL warning rewritten off the ngrok hostname, and
  the two Google redirect URIs recorded as living on *different* hosts, which is
  the part that is easy to get wrong.
- ✅ **`qonvo-up.sh` runs `cloudflared`** instead of ngrok, and now curls both
  public URLs at the end. A tunnel that connects but routes nowhere looks
  identical to a healthy one from the machine it runs on, so the script proves
  the public path rather than assuming it.
- ✅ **Crawl surface verified on the real host** — `robots.txt`, `sitemap.xml`
  and `llms.txt` all serve `https://qonvo.org` URLs with zero ngrok or localhost
  references. Worth re-checking after any rebuild: these come from
  `NEXT_PUBLIC_SITE_URL`, which is baked in at build time.

### Staging on `dev.qonvo.org`

Not exposed, deliberately. Adding it is two steps:

```yaml
# ~/.cloudflared/config.yml, above the catch-all 404
  - hostname: dev.qonvo.org
    service: http://localhost:3012      # the staging dashboard
  - hostname: dev-api.qonvo.org
    service: http://localhost:8010      # the staging API
```
```bash
cloudflared tunnel route dns qonvo dev.qonvo.org
cloudflared tunnel route dns qonvo dev-api.qonvo.org
```

Then set `AUTH_URL`, `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_SITE_URL` in
`dashboard/.env.staging.local` to the dev hosts and rebuild with
`./run-dashboard-staging.sh --build`.

**Google will not work on staging until its redirect URIs are added too** —
`https://dev-api.qonvo.org/api/integrations/oauth/callback` and
`https://dev.qonvo.org/api/auth/callback/google`. Until then staging is
email-and-password only, which is fine for everything except testing the Google
flows themselves.

**Use `dev-api` rather than `api.dev`.** A wildcard certificate covers one label
only, and second-level names like `api.dev.qonvo.org` fall outside it. Cloudflare
issues per-host certificates here so it would work either way, but the flat name
stays portable to the VPS.

Two more things worth doing once staging is public: put `X-Robots-Tag: noindex`
on it (the Caddyfile blocks already have it) so it never competes with
production in search, and give staging its own LLM key — it currently shares
production's, so a test run can exhaust the real quota.
