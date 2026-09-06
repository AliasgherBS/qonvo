# Qonvo deployment, sizing and costs

_Measured on this machine on 2026-09-05, priced against rates checked the same
day. Every resource number below is observed, not estimated, unless it says
otherwise._

---

## 0. What is measured and what is not

Re-verified **2026-09-06 against a real tenant** with `./scripts/measure-usage.sh`
— a live WhatsApp number, a 36-message conversation in Urdu and English, and an
ingested knowledge base. **Two claims were wrong and are corrected below.** Run
the script again after more traffic and update this table.

| Claim | Basis | Status |
|---|---|---|
| ~1,000 tokens per reply | a near-empty dev tenant | ❌ **WRONG — was 3.3x too low.** Real tenant measures **3,312** |
| Container memory ~740 MB (app), ~1.15 GB with monitoring | `docker stats` | ✅ **measured** |
| WAHA base 257 MB | staging with zero sessions | ✅ **measured** |
| WAHA ~22 MB per session | (369 − 257) / 5 sessions | ⚠️ **derived from two points**, not per-session isolation |
| Session disk 24 MB with `fullSync` on | `du` on a real session, 5,511 files | ✅ **measured** |
| Session disk 3–4 MB with `fullSync` off | reasoning about which files stop being created | ❌ **WRONG — measured 11 MB.** See §2.1 for why |
| Messages ~0.5–1 KB steady state | measured 2.3 KB at 50 rows, minus amortising index overhead | ⚠️ **extrapolated** |
| Knowledge chunk 6–8 KB | a 1536-dim float32 vector is 6.1 KB; measured 112 KB at 1 row | ⚠️ **extrapolated** |
| MinIO unused, media not retained | `minio_data` is 4 KB | ✅ **measured** |
| Uploaded files persist after tenant delete | **was true, fixed 2026-09-05** | ✅ **fixed and verified** |
| WAHA `DELETE` frees the session directory | 124 KB directory, gone after the call | ✅ **measured** |
| Postgres `DELETE` does not shrink the file | standard Postgres behaviour | ✅ **true, and worth knowing** |
| Per-tenant ~7 MB first month | built from the rows above | ❌ **WRONG — ~13 MB**, the session dominates |
| AI cost per tenant | rates × **measured** tokens | ⚠️ **modelled on real tokens now**; message volume still assumed |
| Provider rates in §6 | vendor pricing pages, 2026-09-05 | ✅ **checked**, except Uplift AI (not public) |
| Anything about concurrency | — | ❌ **never tested** |

The honest summary: **the two numbers that mattered most were both too optimistic,
and both are now measured.** AI cost per tenant roughly triples; per-tenant storage
roughly doubles. Neither changes the conclusion — the margins are still good — but
the earlier figures came from a machine with no real knowledge base and no real
conversation, which is the wrong shape of data to extrapolate from.

Load behaviour remains untested.

---

## 1. What the system actually costs to run, measured

`docker stats`, production stack, idle:

| Component | RAM | Note |
|---|---:|---|
| waha | **369 MB** | 257 MB base + ~22 MB per session (5 sessions loaded) |
| minio | 80 MB | effectively unused today, see §3 |
| api (uvicorn) | 78 MB | |
| postgres | 68 MB | `shared_buffers` still at the 128 MB default |
| scheduler | 65 MB | |
| worker | 63 MB | |
| redis | 18 MB | |
| **Application subtotal** | **~740 MB** | |
| dashboard (host node) | 105 MB | ~400 MB while building |
| **Production total** | **~845 MB** | |
| prometheus + grafana + alertmanager + node-exporter | 301 MB | opt-in profile |
| **With monitoring** | **~1.15 GB** | |
| staging stack (second copy) | ~640 MB | optional, and stoppable |

CPU at idle is under 1% per container. **The application is I/O-bound**: LLM,
embeddings, STT and TTS are all external HTTP, so nearly all wall-clock per
message is spent waiting on Google or Groq. There is no code path that could use
a GPU, and none should be added while a reply costs a fraction of a cent.

### What actually sizes the box

Not the idle footprint. Three other things:

1. **The Next.js build**, which peaks around 1.5–2.5 GB and wants several cores.
   This alone rules out a 2 GB machine unless you build elsewhere.
2. **Docker images**: ~12 GB before a single row of data (WAHA is 4.1 GB on its
   own, pgvector 621 MB, backend 582 MB), plus build cache.
3. **Per-session WAHA memory**, at ~22 MB each, which is your per-tenant term.

---

## 2. Storage per tenant

### 2.1 WhatsApp session files — measured on a real session

Both configurations are now observed on live sessions:

| | `fullSync` **on** (old) | `fullSync` **off** (current) |
|---|---:|---:|
| Total | **24 MB** | **11 MB** |
| Files | 5,511 | 1,758 |
| `store.sqlite3` | 1.2 MB (27 MB on a busier number) | **4 KB** |
| lid-mapping files | 4,678 | 926 |
| pre-key files | 810 | 811 |

**The fix did what it was for**: the message-history store went from megabytes to
**4 KB**. Turning `fullSync` off stops WhatsApp history being cached, and it did.

**But my 3–4 MB estimate was wrong, because I mis-attributed the cost.** The disk
is not consumed by the store; it is consumed by thousands of tiny JSON files each
occupying a 4 KB filesystem block:

- **811 pre-key files ≈ 3.2 MB.** Signal protocol key material, generated
  regardless of any setting. **This is a fixed floor per session.**
- **926 lid-mapping files ≈ 3.7 MB.** These track the linked phone's address
  book, and `fullSync` only controls whether they are fetched *up front* — they
  still accumulate as contacts are seen.

**The corrected scaling law:**

> **~3.5 MB fixed, plus ~4 KB per contact the linked phone knows about.**

| Linked phone's address book | Session disk |
|---|---:|
| Small (500 contacts) | ~5.5 MB |
| Typical business (2,000) | **~11 MB** ← measured |
| Large (5,000) | ~23 MB |
| Very large (15,000) | ~63 MB |

Still far better than `fullSync` on, where a five-year-old retail number was
heading for hundreds of megabytes of message history on top. But **a tenant's
session cost is driven by their phone's contact list, not by their Qonvo usage** —
which is worth knowing, because it means a quiet tenant with a huge address book
costs more disk than a busy one with a small phonebook.

### 2.2 Postgres, measured

Whole database: **12 MB**. Per-row costs are still index-dominated at these
volumes (36 messages, 3 chunks), so treat them as ceilings:

| Table | Measured | Steady-state estimate |
|---|---:|---|
| `messages` | 3.2 KB/row at 36 rows | ~0.5–1 KB/message |
| `knowledge_chunks` | 48 KB at 3 rows | ~6–8 KB/chunk (a 1536-dim vector is 6.1 KB) |

**Per tenant, corrected:**

| Item | Size |
|---|---:|
| WhatsApp session files | **~11 MB**, one-off, scales with the address book |
| 2,000 messages (in + out) | ~2 MB/month |
| Knowledge base, 100 chunks | ~0.7 MB, one-off |
| Uploaded source files | 64 KB observed for one document |
| **First month** | **~13 MB** |
| **Each month after** | **~2 MB** |

100 tenants ≈ **1.1 GB in the first month**, then ~200 MB/month. Still not the
constraint, but roughly double the earlier figure.

### 2.3 MinIO is currently unused

`minio_data` is 4 KB. Media is downloaded for transcription and referenced by its
WAHA URL, never copied into object storage. That is fine and cheap, but note the
consequence: **media is not retained**, so a voice note is unplayable in the
inbox once WAHA drops it. If you later want playback history, that is when MinIO
starts costing something (roughly 60 KB per 30-second note).

---

## 3. Sizing

| Tier | Live sessions | vCPU | RAM | NVMe | Why |
|---|---:|---:|---:|---:|---|
| Pilot | 1–10 | 4 | 8 GB | 160 GB+ | Handles the build; ~1.2 GB used, rest is headroom |
| Growth | 10–40 | 4–6 | 16 GB | 320 GB | WAHA memory is the term that grows |
| Scale | 40+ | 8 | 32 GB | 500 GB | Or shard WAHA across instances |

**Start at 4 vCPU / 8 GB / 160 GB+.** The commonly quoted "40–80 GB disk" for a
box like this is too small once 12 GB of images and nightly backups are counted.

**One thing genuinely unknown:** nothing has ever been load-tested. The numbers
above are a resource profile, not a throughput measurement. Before promising
anyone concurrency, run one.

---

## 4. Where to host it

Prices checked 2026-09-05. Hetzner raised prices twice in 2026, which changes the
usual answer. **See §7 before buying — being in Pakistan rules some of these out
in practice, whatever the price says.**

| Provider | Plan | vCPU | RAM | Disk | Monthly | Verdict |
|---|---|---:|---:|---:|---:|---|
| **Netcup** | VPS Lite 2 G12s | 4 shared | 8 GB | 160 GB SSD | **€6.65** (~$7.2) | **Exact match for the spec above.** Quarterly billing, no lock-in |
| **Netcup** | RS 1000 G12 | 4 **dedicated** | 8 GB DDR5 ECC | 256 GB NVMe | ~€10.74 (~$11.6) | Dedicated cores. Buy this if shared cores prove noisy |
| **Contabo** | Cloud VPS 4 | 4 shared | 8 GB | **100 GB** | $5.28 / $6.60 | Cheapest headline, but **disk is under the 160 GB floor** |
| **Contabo** | Cloud VPS 6 | 6 shared | 12 GB | 200 GB | $7.20 / $9.00 | The Contabo plan that actually fits. **Easiest to buy from Pakistan** (§7) |
| Hetzner | CX33 | 4 shared | 8 GB | 80 GB | €25.47 | Great network, now expensive, tight disk, **and the hardest to get verified** |
| Hetzner | CX23 | 2 shared | 4 GB | 40 GB | €5.49 | Too small: the Next.js build will not fit |
| Hostinger | KVM 4 | 4 | 16 GB | 200 GB | $12.99 → **$28.99** | Renewal more than doubles |
| DigitalOcean | equivalent | 4 | 8 GB | 160 GB | ~$48 | Convenient, ~4x Netcup |

Whichever you pick: build images on the box, keep the monitoring profile off
until you need it, and stop the staging stack when you are not using it.

### 4.1 Cloudflare Containers: priced, and the answer is no

Worth checking because the pricing model looks cheap at a glance. It is not
cheap for this workload, and cost is the *second* problem.

**The rates**, on the Workers Paid plan at $5/month: memory $0.0000025 per
GiB-second with 25 GiB-hours included; CPU $0.000020 per vCPU-second with 375
vCPU-minutes included, billed on actual use; disk $0.00000007 per GB-second with
200 GB-hours included. Egress from Pakistan falls in "Everywhere Else" at
$0.04/GB with 500 GB included.

A month is 730 hours, or 2,628,000 seconds. Qonvo needs its services **up all the
time**, so every one of those seconds is billable.

| Line | `standard-3` (2 vCPU, 8 GiB, 16 GB) | `standard-4` (4 vCPU, 12 GiB, 20 GB) |
|---|---:|---:|
| Memory, provisioned 24/7 | $52.34 | $78.62 |
| Disk, provisioned 24/7 | $2.89 | $3.63 |
| CPU at 10% average | $10.06 | $20.57 |
| Workers Paid plan | $5.00 | $5.00 |
| **Monthly** | **~$70** | **~$108** |
| Same at 25% average CPU | ~$96 | ~$139 |

Against the table above:

| Option | vCPU | RAM | Disk | Monthly |
|---|---:|---:|---:|---:|
| **Contabo VPS S** | 4 | 8 GB | 200 GB **persistent** | **~$7** |
| Netcup RS 1000 G12 | 4 dedicated | 8 GB | 256 GB **persistent** | ~$11.60 |
| CF Containers `standard-3` | 2 | 8 GiB | 16 GB **ephemeral** | ~$70 |
| CF Containers `standard-4` | 4 | 12 GiB | 20 GB **ephemeral** | ~$108 |

**Ten to twenty times the price for less disk**, and that is one container. Qonvo
runs api, worker, scheduler, Postgres, Redis, WAHA, MinIO, Caddy and the
dashboard.

#### Cost is not why it fails

**All container disk is ephemeral.** Cloudflare's own wording: when an instance
goes to sleep, the next start gives it *"a fresh disk as defined by its container
image"*. Persistent disks are *"not slated for the near future"*. That deletes,
on every sleep:

- the Postgres data directory
- **the WAHA session files**, which is a QR re-scan for every tenant
- MinIO objects

**Scale-to-zero is the product, and it is exactly what breaks this.** The pricing
model rewards idling. WAHA holds a live connection to WhatsApp; if it sleeps, the
session drops. The one feature that makes Containers cheap is the one Qonvo
cannot use, so you would pay always-on rates on a platform designed for bursty
work.

**The disk ceiling is 20 GB**, against the 160 GB+ §3 calls for once images and
nightly backups are counted. Memory caps at 12 GiB per instance, so the Scale
tier (32 GB) has no path at all.

You could push state into R2, D1 and Durable Objects, but that is not a
deployment change, it is rewriting the persistence layer of a working product to
pay more for it.

#### Where it would make sense

Genuinely bursty, stateless work that idles most of the day: an image build, a
one-off bulk knowledge ingestion, a PDF renderer. If knowledge ingestion ever
becomes spiky enough to need its own box, this is the right shape for that one
job. The stateless Next.js dashboard could also live at the edge, though Workers
or Pages is cheaper than Containers for that.

**Verdict: stay on the VPS.** Contabo VPS S at ~$7 is the recommendation, and
nothing about Containers changes it.


### 4.2 Head to head, from the quoted prices

Both quotes in hand, against the §3 floor of **4 vCPU / 8 GB / 160 GB+**.

**Contabo**, 24-month prepaid price first, undiscounted second:

| Plan | vCPU | RAM | SSD | 24 mo | List | Port |
|---|---:|---:|---:|---:|---:|---:|
| Cloud VPS 4 | 4 | 8 GB | **100 GB** | $5.28 | $6.60 | 200 Mbit/s |
| Cloud VPS 6 | 6 | 12 GB | 200 GB | $7.20 | $9.00 | 300 Mbit/s |
| Cloud VPS 8 | 8 | 24 GB | 300 GB | $13.44 | $16.80 | 600 Mbit/s |
| Cloud VPS 12 | 12 | 48 GB | 400 GB | $24.00 | $30.00 | 800 Mbit/s |
| Cloud VPS 16 | 16 | 64 GB | 500 GB | $35.60 | $44.50 | 1 Gbit/s |
| Cloud VPS 18 | 18 | 96 GB | 600 GB | $47.04 | $58.80 | 1 Gbit/s |

**Netcup VPS Lite G12s**, monthly, 0% VAT, no discount tiers to game:

| Plan | vCore | RAM | SSD | €/mo | ~$/mo |
|---|---:|---:|---:|---:|---:|
| piko G11s | 1 | 1 GB | 30 GB | €1.54 | $1.7 |
| nano G11s | 2 | 2 GB | 60 GB | €2.58 | $2.8 |
| Lite 1 G12s | 2 | 4 GB | 80 GB | €4.10 | $4.4 |
| **Lite 2 G12s** | **4** | **8 GB** | **160 GB** | **€6.65** | **$7.2** |
| Lite 3 G12s | 8 | 16 GB | 320 GB | €11.67 | $12.6 |
| Lite 4 G12s | 16 | 32 GB | 640 GB | €21.61 | $23.3 |

#### The comparison that matters

`Cloud VPS 4` looks like the winner at $5.28 and is not eligible: **100 GB is
below the 160 GB floor**, and adding storage at Contabo is a one-way ratchet
(below). The real Contabo entry is `Cloud VPS 6`.

| | Contabo Cloud VPS 6 | Netcup VPS Lite 2 G12s |
|---|---|---|
| CPU / RAM / disk | 6 shared / 12 GB / 200 GB | 4 shared / 8 GB / 160 GB |
| Headline price | $7.20/mo | €6.65/mo (~$7.2) |
| **What that price requires** | **24 months prepaid, $172.80 up front** | **Nothing. It is the price** |
| True monthly | **$9.00** | €6.65 |
| 12-month rate | $7.65 ($91.80 up front) | n/a |
| Billing cycle | 1, 12 or 24 months | 3 months (~€19.95) |
| Minimum contract | none monthly | 3 months |
| Port | 300 Mbit/s | 750 Mbps, throttled to 100 if the 24h average exceeds 100 |
| Snapshots | 2 | Copy-on-write, unlimited by count |
| Extra storage later | Plan upgrade or Storage Extension. **Downgrades impossible**, and you must repartition by hand | **Local Block Storage, expandable to 4 TB** |

**Contabo Cloud VPS 6 is the better value, and it is not close on unit price.**
Netcup is cheaper in absolute terms, but you get less of everything:

| | $/mo | $/vCPU | $/GB RAM | $/GB disk |
|---|---:|---:|---:|---:|
| Contabo VPS 6, monthly | $9.00 | $1.50 | $0.75 | $0.045 |
| Contabo VPS 6, 24 mo | $7.20 | $1.20 | $0.60 | $0.036 |
| Netcup Lite 2 | ~$7.20 | $1.80 | $0.90 | $0.045 |

At its **monthly** rate Contabo is ~17% cheaper per core and per GB of RAM, with
identical disk pricing, for $1.80 more a month in absolute terms. It also buys
real runway: 6 vCPU / 12 GB sits between the Pilot and Growth rows in §3, and
**WAHA memory is the term that grows**. Netcup Lite 2 is exactly Pilot and
nothing beyond it.

**The 24-month discount is not worth taking.** $9.00 → $7.20 saves $1.80/month
against locking two years and $172.80 up front, on a product that has **never
been load-tested** (§3) and may need to move. The 12-month tier at $7.65 saves
$1.35/month for half the lock-in and is the better of the two if you commit at
all. Best of the three: **run monthly at $9.00 until the load test exists.**
$1.80/month is cheap optionality.

**And §7.2 points the same way.** Contabo takes PayPal, which is exactly the
send-only mode a Pakistani account has. Netcup leans SEPA with German KYC, so it
may not be buyable at all. Better value *and* easier to buy is not a close call.

Netcup keeps two genuine edges, neither decisive here: a faster port (750 Mbps
against 300 Mbit/s) and cleaner storage growth (Local Block Storage to 4 TB,
versus Contabo's one-way upgrade and manual repartition). If disk I/O or
throughput ever becomes the measured bottleneck, that is when to revisit.

One more distinction the earlier table blurred: **VPS Lite is shared cores, RS is
dedicated.** Both sit on the same EPYC 9645 hardware; only the guarantee differs.
Qonvo is mostly I/O-bound — Postgres, retrieval, HTTP out to the model — so
shared cores are fine at pilot scale. If a noisy neighbour shows up, `RS 1000
G12` at ~€10.74 is the same shape with dedicated cores.

---

### 4.3 The add-ons: what to buy and what to skip

| Add-on | Price | Verdict |
|---|---:|---|
| Contabo **Auto Backup** | $4.00/mo | **Buy it.** See below |
| Contabo UK region | +$2.00/mo | **No.** The EU region is both cheaper (free) and *closer*: 124 ms vs 147 ms (§7.3) |
| Contabo 400 GB SSD | +$3.60/mo | **Not yet.** 200 GB clears the 160 GB floor with room |
| Contabo cPanel / Plesk / Windows | +$27.50 / $15.00 / $20.40 | **No.** Docker Compose on Ubuntu, no control panel in the stack |
| Contabo Private Networking | free, off | **No.** Single box |
| Contabo Object Storage | free, none | **No.** MinIO is self-hosted and currently holds nothing (§2.3) |
| Netcup IPv6-only | −€0.50/mo | **No.** Saving €0.50 to drop IPv4 breaks reachability for a public API |
| Netcup `.dev` domain | €1.50/mo | **No.** €18/yr against Cloudflare at cost (§5) |

#### Why backup is the one worth buying

`scripts/backup.sh` dumps Postgres, the WAHA session volume and the MinIO bucket
to a **local** directory, and mirrors **only MinIO** offsite when
`BACKUP_MINIO_TARGET` is set. MinIO is the one thing in that list holding no data
(§2.3). So today the offsite copy covers nothing, and the two things that would
actually end the business if the disk died — **the Postgres database and the WAHA
session files** — exist only on the box being backed up.

Two ways to close it:

1. **Contabo Auto Backup, $4/month.** Daily whole-VM backup stored off-server,
   last 10 kept, one-click restore. Covers disk failure and ransomware. It does
   **not** cover losing the Contabo account itself, since it is the same vendor.
2. **Extend `backup.sh`** to push the Postgres dump and the WAHA tarball to
   Cloudflare R2 or Backblaze B2. R2 gives 10 GB free with **zero egress fees**,
   so restoring costs nothing, and it survives the provider disappearing.

Option 2 is better and nearly free; option 1 is available this afternoon. The
$4/month is already budgeted in §9. **Do 1 now, 2 this month**, and stop
pretending the current offsite mirror protects anything.


---

## 5. The domain

`qonvo.org` is fine and matches what is already configured. Two things first:

- **Check `qonvo.com`.** It did not resolve when probed, which hints it may be
  free. For a commercial product `.com` is materially better: `.org` reads as
  non-profit to a business buyer, and you will be saying this domain out loud to
  Pakistani business owners who will assume `.com`.
- Register where renewal equals registration. **Cloudflare Registrar sells `.org`
  at cost, about $8.50/year**, no renewal jump, free WHOIS privacy. Porkbun is
  the same. Namecheap and GoDaddy discount year one and recover it later.

Changing the domain touches four coupled places: `AUTH_URL`,
`QONVO_GOOGLE_OAUTH_REDIRECT_BASE`, `QONVO_DASHBOARD_BASE_URL`, and the Google
Cloud console redirect URIs.

### 5.1 Email, which is attached to the domain

> Step by step setup, DNS records and the migration path is in
> [`EMAIL-SETUP.md`](EMAIL-SETUP.md). This section is only what it costs.

Two different jobs get conflated under "email", and they are bought separately.

- **Sending** — password resets, welcome mails, owner alerts. Machine to human,
  from `noreply@`. Needs a *transactional API*, not a mailbox.
- **Receiving and replying** — support, billing, MoR paperwork, service signups.
  Human to human. Needs an *inbox*, or at least forwarding.

A mailbox cannot send bulk transactional mail without wrecking its reputation,
and a transactional API cannot receive anything. You need one of each.

#### The cheapest stack that actually works: $0/month

| Job | Choice | Cost |
|---|---|---:|
| Receive on `@qonvo.org` | **Cloudflare Email Routing** | **$0** |
| Reply as `@qonvo.org` | Gmail *Send mail as* over the provider's SMTP | $0 |
| Send transactional | **Brevo** 300/day, or **Resend** 3,000/month | $0 |

Cloudflare Email Routing is free with **200 addresses and 200 destinations per
domain**, no message-count limit, plus a catch-all. It forwards into the Gmail
you already use. It is **forward-only** — it cannot send — which is why replies
go out through Gmail's *Send mail as* pointed at an SMTP relay. Brevo hands you
free SMTP credentials that serve as that relay and as the app's transactional
sender, so one free account covers both.

That is genuinely $0/month on top of the domain, and it is enough until you are
sending thousands of mails a day or want an inbox that is not your personal one.

#### What each tier costs when you outgrow free

| Product | What it is | Price |
|---|---|---:|
| Cloudflare Email Routing | Forwarding only, no mailbox | **$0** |
| Zoho Mail Free | Real mailbox, 5 users, 5 GB, **webmail only, no IMAP/POP**, and no longer offered to new signups in every region | $0 |
| **Zoho Mail Lite** | Real mailbox with IMAP/POP, 5 GB | **$1/user/mo** billed yearly, $1.25 monthly |
| Migadu Micro | Unlimited domains, mailboxes and aliases; limits are on daily volume | $19/yr |
| Purelymail | Unlimited domains and accounts, 10 GB | from $49/yr |
| Google Workspace | The default nobody gets fired for | $7/user/mo |
| Microsoft 365 Business Basic | Same, with Office | $6/user/mo |
| Brevo | Transactional API + SMTP, **300/day (~9,000/mo)** free, marketing too | $0 |
| Resend | Transactional API, 3,000/mo but **capped at 100/day**, 3 domains | $0 |
| Resend Pro | 50,000/mo, no daily cap, 10 domains | $20/mo, $0.90 per extra 1,000 |
| Amazon SES | Cheapest at scale, most setup | **$0.10 per 1,000** |
| Mailgun free | Testing volumes only | $0, 100/day |

Resend's **100/day** cap is the trap in its free tier: the monthly figure reads
generous and the daily one is what actually binds. Brevo's 300/day is three
times more headroom for the same $0. At real volume nothing beats SES: 100,000
mails is **$10**.

#### You do not need a mailbox per purpose

The instinct to buy `support@`, `billing@`, `noreply@` and `marketing@` as four
paid users is wrong, and at $1–7 each it is a recurring waste.

- **`noreply@` needs no mailbox at all.** It only sends, from the transactional
  provider. Nobody logs into it.
- **`support@`, `billing@`, `hello@`, `admin@` are aliases** onto one inbox.
  Cloudflare gives 200 for free; Zoho and Migadu give unlimited.
- **Marketing is not a mailbox problem, it is a reputation problem.** Solve it
  with a subdomain, not a second account.

So: **one mailbox, many aliases, one sending domain per reputation class.** One
paid seat at $1/month is the entire mailbox bill for a long time.

#### Split sending by reputation, not by department

Separate subdomains carry separate sender reputations, which is the whole point.
A marketing blast marked as spam must not be able to stop your password resets
arriving.

| Domain | Carries | Risk |
|---|---|---|
| `qonvo.org` | Human mail: support, billing, corporate | Low volume, keep it clean |
| `send.qonvo.org` | Transactional: resets, welcome, owner alerts | Must never be marked spam |
| `news.qonvo.org` | Marketing, if and when | Highest risk, isolated on purpose |

Each needs its own SPF, DKIM and DMARC. Do not send marketing from the root
domain, and do not send transactional from the marketing subdomain.

#### Using it to buy things, and to register with a merchant of record

Yes, and you should. Any address that receives mail works for signing up to a
service, and Cloudflare forwarding receives fine, so a $0 setup is enough to
register for Polar, a VPS, or a domain.

Use a **role address you keep**, `billing@qonvo.org`, rather than a personal
Gmail, for three practical reasons: the account survives you changing personal
email, MoR invoices and KYC correspondence land somewhere findable, and a
merchant of record running business verification on a personal Gmail is a
slightly worse first impression than one on the domain it is verifying.

One caveat that catches people: some services refuse **forward-only** addresses
for account recovery, and a few block known forwarders. If Polar or a bank
rejects the address, that is the point to spend $1/month on a real Zoho mailbox,
not before.


---

## 6. AI providers, priced model-agnostically

The adapter is one OpenAI-compatible client, so **any of these is a config
change, not a code change**. What you run today (Gemini 2.5 Flash, Groq Whisper,
Groq Orpheus) was chosen for a free tier, not on merit.

### 6.1 The unit that makes these comparable

A real tenant measures **3,312 tokens per reply** — a live number, a knowledge
base, and a 36-message conversation. The earlier figure of ~1,000 came from a
dev tenant with one knowledge chunk and no conversation history, and was **3.3x
too low**.

Where the tokens go, and why this is the right number to plan with:

| Component | Cap | Behaviour |
|---|---:|---|
| Retrieved knowledge (RAG) | 2,000 tokens | Fills up once a tenant has a real knowledge base |
| Conversation history | 4,000 tokens | Grows with the thread, then the rolling summary compresses it |
| System prompt + persona | ~300 tokens | Fixed |

So the true range is roughly **1,000 tokens for a first message to a
knowledge-less tenant, up to ~6,500 for a long conversation against a full
knowledge base.** 3,312 is a working tenant mid-conversation, which is what to
budget for.

Cost of **1,000 replies** is therefore `3.15 × input_price + 0.16 × output_price`
(WhatsApp replies are short; output is assumed at ~160 tokens).

### 6.2 Language models

| Model | $/1M in | $/1M out | **Per 1,000 replies** |
|---|---:|---:|---:|
| Gemini 2.5 Flash-Lite *(retires 16 Oct 2026)* | $0.10 | $0.40 | **$0.38** |
| DeepSeek V4 Flash | $0.14 | $0.28 | **$0.49** |
| Gemini 2.5 Flash *(current)* | $0.15 | $1.25 | **$0.67** |
| GPT-5.6 Luna | $0.20 | $1.20 | **$0.82** |
| GPT-5 mini | $0.25 | $2.00 | **$1.11** |
| MiniMax M2.7 / M3 | $0.30 | $1.20 | **$1.14** |
| DeepSeek V4 Pro | $0.435 | $0.87 | **$1.51** |
| Gemini 3.5 Flash | $0.75 | $4.50 | **$3.08** |
| Claude Haiku 4.5 | $1.00 | $5.00 | **$3.95** |
| Kimi K2.6 | $1.20 | $4.50 | **$4.50** |
| GLM-5.3 (Z.ai) | $1.40 | $4.40 | **$5.11** |
| GPT-5 | $1.25 | $10.00 | **$5.54** |
| Gemini 3.1 Pro / GPT-5.6 Terra | $2.00 | $12.00 | **$8.22** |
| Claude Sonnet 5 | $3.00 | $15.00 | **$11.85** |
| Claude Opus 5 | $5.00 | $25.00 | **$19.75** |
| GPT-5.6 Sol | $5.00 | $30.00 | **$20.55** |
| Claude Fable 5 | $10.00 | $50.00 | **$39.50** |

Qwen3.7 Max benchmarks competitively; no published rate confirmed.

**The input side now dominates completely** — 95% of the spend is the prompt, not
the answer. Two consequences:

1. **Prompt caching is no longer optional.** Gemini charges $0.03/M for cache
   reads against $0.15/M fresh, so caching the stable prefix (system prompt +
   persona) cuts the bill materially. Qonvo does not use it yet, and at 3,312
   tokens a reply that is now the single biggest saving available.
2. **Model choice matters more than it did.** At the old 1,000-token figure,
   cheapest-to-Haiku was $1.48 per tenant. It is now **$3.28**, and
   cheapest-to-Sonnet is $11.18. Still small against a $10 subscription, but no
   longer noise.

Practical shortlist unchanged: **Gemini 2.5 Flash** ($0.67), **DeepSeek V4
Flash** ($0.49) for the floor, **Claude Haiku 4.5** ($3.95) if the tool loop
needs better instruction-following.

### 6.3 Text to speech — read this before choosing

**Your current TTS cannot speak Urdu.** `canopylabs/orpheus-v1-english` is
English-only (Groq also offers an Arabic variant). For a Pakistani market that is
not a pricing question, it is a "the feature does not work" question.

| Provider / model | $/1M chars | Per 100 voice replies (400 chars) | Urdu? |
|---|---:|---:|---|
| Speechify | $10 | $0.40 | unclear |
| OpenAI `tts-1` | $15 | $0.60 | **yes** (multilingual) |
| **Groq Orpheus English** *(current)* | $22 | $0.88 | **no** |
| Deepgram Aura-2 | $30 ($27 at Growth) | $1.20 | no |
| Groq Orpheus Arabic | $40 | $1.60 | no |
| Cartesia (Startup, $49/1.25M) | ~$39 effective | ~$1.57 | limited |
| Groq PlayAI Dialog | $50 | $2.00 | no |
| ElevenLabs Turbo/Flash v2.5 | $50 | $2.00 | **yes** |
| MiniMax speech | $60–100 | $2.40–4.00 | limited |
| ElevenLabs v3 / Multilingual v2 | $100 | $4.00 | **yes** |
| **Uplift AI (Orator)** | **not published** | — | **yes, purpose-built** |

**Uplift AI is the one to evaluate first.** It is a Pakistani, Y Combinator
backed voice startup ($3.5M seed, Indus Valley Capital) building specifically for
Urdu, Sindhi and Balochi, with Punjabi and Saraiki announced. Khan Academy used
its Orator model for 2,500 Urdu videos and Syngenta is building farmer-facing
voice assistants on it. It claims "60x more cost-effective" than incumbents, but
**pricing requires a sign-up** — the site returns 403 to automated fetches and
the docs carry no rates. Ask them directly; a local vendor is also easier to pay
from Pakistan than most of this table.

The realistic comparison is **Uplift AI versus ElevenLabs versus OpenAI `tts-1`**
for Urdu quality. ElevenLabs is 3–7x the price of `tts-1`; whether it is worth it
is a listening test, not a spreadsheet.

### 6.4 Speech to text

Urdu is much less of a problem here — Whisper handles it, and it is already
verified working on this deployment.

| Provider / model | $/hour | Per 50 min/month |
|---|---:|---:|
| **Groq whisper-large-v3-turbo** | **$0.04** | $0.03 |
| Soniox | ~$0.10 | $0.08 |
| AssemblyAI Universal-3.5 Pro | $0.21 | $0.18 |
| ElevenLabs Scribe v2 | $0.22 | $0.18 |
| Deepgram Nova-3 (batch) | $0.26 | $0.22 |
| Groq whisper-large-v3 *(current)* | ~$0.11 | $0.09 |
| Rev AI Reverb | $0.18 | $0.15 |
| OpenAI Whisper | $0.36 | $0.30 |
| Deepgram Nova-3 (streaming) | $0.46 | $0.38 |
| Speechmatics (batch) | $0.80 | $0.67 |
| Google Chirp 2 | $0.96 | $0.80 |
| Azure Speech | $1.02 | $0.85 |
| AWS Transcribe | $1.44 | $1.20 |

**Switching to `whisper-large-v3-turbo` on the same Groq key cuts STT ~64%** and
is a one-line model change. STT is your cheapest AI line either way.

### 6.5 What a tenant actually costs, by choice

1,000 messages/month, 10% arriving as voice, voice replies on, priced at the
**measured** 3,312 tokens per reply:

| Configuration | LLM | STT | TTS | **Total** |
|---|---:|---:|---:|---:|
| Floor (DeepSeek Flash + Groq turbo + `tts-1`) | $0.49 | $0.03 | $0.60 | **$1.12** |
| Current (Gemini 2.5 Flash + Groq v3 + Orpheus) | $0.67 | $0.09 | $0.88 | **$1.64** |
| Urdu-capable (Gemini Flash + turbo + ElevenLabs Flash) | $0.67 | $0.03 | $2.00 | **$2.70** |
| Premium (Claude Haiku + turbo + ElevenLabs v3) | $3.95 | $0.03 | $4.00 | **$7.98** |
| Text only, floor | $0.49 | — | — | **$0.49** |

Voice is still the largest single line in every row that has it (54–74%), but the
LLM is no longer negligible: it went from 25% of the current configuration to
41%. **Both levers now matter** — `voice_reply_mode` for the big win, prompt
caching for the rest.

### 6.6 Two corrections to make

- **`config.py` prices Gemini 2.5 Flash at $0.30/$2.50** — the OpenRouter rate.
  Google direct is $0.15/$1.25, so you are over-reporting AI cost by 2x.
- **Model IDs expire.** Gemini 2.5 Flash-Lite retires 16 October 2026. A pinned
  model is a dependency with a deadline; the per-tenant provider override exists
  precisely so a retirement is a settings change.

---

## 7. Buying any of this from Pakistan

Price lists assume you can pay. From Pakistan several of these are harder to buy
than they are to afford, and that changes the recommendation.

### 7.1 The payment constraint

- **Pakistani cards ship with international e-commerce disabled.** Allied, MCB,
  Askari, Bank AL Habib and HBL all require you to enable it explicitly, by app
  or phone call.
- **Limits are low** once enabled — commonly **$100–500/month**, which is fine
  for a $12 VPS but will bind as AI spend grows.
- **PayPal works only one way.** Pakistan has had send-and-purchase PayPal since
  2018 but cannot *receive*. For buying hosting that is enough; for collecting
  customer revenue it is not.
- Decline rates are higher on cross-border merchants regardless of limits.

**Workarounds, in order of how much friction they add:** enable international use
on an existing card and raise the limit; **Payoneer**, the default for Pakistani
freelancers and the one with the paperwork trail FBR expects; a **virtual USD
card funded by USDT**, which needs no bank approval; or **local providers**
(RapidCompute, TezHost, CloudServers.pk, Nayatel) that take JazzCash, Easypaisa
and PKR transfer — basic VPS, but no currency problem at all.

### 7.2 This changes the hosting recommendation

| Provider | Buying from Pakistan |
|---|---|
| **Contabo** | **Easiest.** Card **and PayPal**, and PayPal's send-only mode is exactly what you have. No crypto |
| **Netcup** | Best value, but German KYC and SEPA-leaning payment. Confirm before relying on it |
| **Hetzner** | **Highest risk.** ID verification is strict and opaque for non-EU customers, with Pakistani users specifically reporting rejections and no clear appeal (`cda-review@hetzner.com` is the escalation) |

**Revised recommendation: start on Contabo.** Netcup's dedicated cores are the
better machine, but a server you cannot buy is worth nothing, and Contabo is
~$7/month with 200 GB — enough for everything in §3. Move to Netcup later if you
want the dedicated cores and payment turns out to be easy.

### 7.3 Latency, which nobody mentions until it is slow

German datacentres are ~120–150 ms from Pakistan. Closer options:

| Region | From Pakistan |
|---|---|
| Dubai / UAE | 60–70 ms on Transworld-transit ISPs, but **up to 350 ms on PTCL** |
| Singapore | ~80 ms from Karachi, 130–150 ms elsewhere on PTCL |
| Mumbai | Closest geographically; political routing risk |
| Germany | 120–150 ms, consistent across ISPs |

**This matters less than it looks.** Customers reach the bot through WhatsApp's
own infrastructure, not your server, so their latency is unaffected. Only the
owner's dashboard feels it, and a consistent 130 ms is fine for that. **Consistency
beats the best case here**: Dubai is faster on some ISPs and five times worse on
PTCL, which is the largest. Germany's boring 130 ms is the safer default.

### 7.4 The same constraint applies to the AI providers

Google AI Studio, OpenAI, Groq and Anthropic all bill an international card, so
every §6 option depends on the same card working. Two consequences worth
planning for: **prepaid credit models (OpenAI, Anthropic, DeepSeek) are easier**
than uncapped monthly billing when your card has a $200 ceiling, and **Uplift AI
being Pakistani may make it the only voice vendor you can pay in PKR** — worth as
much as its Urdu quality.

And the real one: **collecting revenue is harder than spending it.** PayPal
cannot receive in Pakistan, so the merchant-of-record question is not "Paddle or
Polar" but "which of them pays out to a Pakistani entity at all". Confirm that
before building anything else around billing.

## 8. Postgres: keep it in-house, for now

| Option | Monthly | For | Against |
|---|---:|---|---|
| **Self-hosted on the VPS** (today) | **$0** | Already built and backed up; no egress; unlimited databases; staging is free | You are the DBA; no automatic failover |
| Supabase Pro | $25 + compute | Managed backups, HA path, Postgres with RLS (a natural fit for this schema) | 2–3× the entire VPS bill for 12 MB of data |
| Neon / RDS | $20–50+ | Autoscaling, PITR | Same objection, plus egress |

**Recommendation: stay self-hosted.** Your entire database is 12 MB, backups now
run nightly and are verified, and a managed instance would cost more than the
server it would sit beside. The industry rule of thumb — managed databases cost
3–10× self-hosted and are worth it when you have no one to run them — points at
managed only once downtime costs you real money.

**Revisit when any of these becomes true:** a paying customer needs an uptime
commitment you cannot personally honour at 3am; the database outgrows the box's
RAM; or you need point-in-time recovery rather than nightly dumps.

One thing to do regardless, and cheaply: **get the backups off the machine.** A
nightly copy to a Hetzner Storage Box (~€3.81/month) or any S3 bucket removes the
single worst failure mode you currently have, which is that the backups live on
the disk they are protecting.

---

## 9. Total cost of ownership

| Line | Monthly |
|---|---:|
| VPS (Contabo VPS S; Netcup ~$12 if payment works) | ~$7 |
| Domain (.org at cost, amortised) | $0.71 |
| Offsite backup (optional, recommended) | ~$4 |
| WAHA | **$0** — everything moved into the free Core in 2026.6.1, no session limit |
| Email (Cloudflare Routing + Brevo free tier) | **$0** — see 5.1; $1/mo if you want a real mailbox |
| Monitoring (self-hosted) | $0 |
| **Fixed total** | **~$12/month** |
| AI, per tenant | +$0.49 text-only floor / +$1.64 current / +$2.70 Urdu-capable voice |

Priced with the Urdu-capable voice stack at the **measured** token rate
($2.70/tenant), the realistic configuration for this market:

| Tenants | Fixed | AI | Total | Revenue at $10/tenant | Margin |
|---:|---:|---:|---:|---:|---:|
| 5 | $12 | $14 | **$26** | $50 | 49% |
| 20 | $12 | $54 | **$66** | $200 | 67% |
| 50 | $12 | $135 | **$147** | $500 | 71% |
| 100 | $24 (bigger box) | $270 | **$294** | $1,000 | 71% |

Text-only tenants cost a fifth of that, so the voice mix still moves the margin
more than the tenant count does. Margins dropped 3–4 points against the earlier
estimate once real token usage was measured — the business case is unchanged.

The economics work because WAHA has no per-message fee. **Payment processing
takes a comparable cut to your entire infrastructure** — a merchant of record
charges roughly 5%, which at 100 tenants is $50/month against $294 of
infrastructure.

---

## 10. Scaling path

Do these in order, and only when the trigger fires.

| Trigger | Move |
|---|---|
| More than ~40 sessions, or WAHA memory climbing | Shard WAHA across instances. Per-session webhooks and tenant resolution already support it |
| The build competes with serving | Build images in CI, pull on the box |
| Postgres CPU is the bottleneck | Tune `shared_buffers` (still at the 128 MB default) before buying anything |
| A customer needs an uptime guarantee | Managed Postgres with failover, and a second app node |
| A customer needs zero ban risk, or you want broadcast | Add the official WhatsApp Cloud API provider |

Nothing here needs Kubernetes, and adding it before the first trigger would cost
more in complexity than it could possibly save.

---

## 11. Open decisions

| Decision | Recommendation |
|---|---|
| **TTS (urgent)** | Orpheus English **cannot speak Urdu**. Evaluate Uplift AI first, then ElevenLabs and OpenAI `tts-1` |
| VPS | **Contabo Cloud VPS 6, monthly at $9.00.** Best value per core and per GB, and the easiest to buy from Pakistan (4.2, 7.2). Skip Cloud VPS 4: 100 GB is under the floor. Do **not** prepay 24 months before a load test exists. Netcup VPS Lite 2 at €6.65 is the fallback if Contabo disappoints on I/O |
| Backups | Contabo Auto Backup $4/mo now; extend `backup.sh` to push Postgres and WAHA offsite to R2 this month. The current offsite mirror covers MinIO, which is empty (4.3) |
| Domain | Check `qonvo.com` first; otherwise `qonvo.org` at Cloudflare |
| LLM | Any cheap-tier model works; pick on reliability. $1.48/tenant separates cheapest from Claude Haiku |
| STT | Move to `whisper-large-v3-turbo`, same key, ~64% cheaper |
| **Prompt caching** | Not used. Input is now 95% of LLM spend, and cache reads are 5x cheaper — the largest saving available |
| **Provider quota** | Free Gemini was hit again on 2026-09-05 and killed a live test mid-run. The 429 named `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: 20`, on `gemini-2.5-flash` — a **per-day** id, not the per-minute limit recorded earlier. Worth confirming which binds. Either way: enable billing before any demo, and note the failure is invisible to owner and customer alike |
| Database | Self-hosted; get backups offsite this month |
| Price table | Correct Gemini to $0.15/$1.25 |
| Payments in | **Answered: Polar lists Pakistan as a supported payout country**, via Stripe Connect Express. Paddle does not block Pakistan either. Confirm the receiving method before building on it |
| Email | Cloudflare Email Routing + Brevo, $0. Add Zoho Mail Lite at $1/user/mo only when a forwarded address is refused or you want a non-personal inbox |
| Load test | Do one before promising concurrency |
| **Cloudflare Containers** | **Evaluated and rejected** (4.1). 10-20x the VPS cost, 20 GB ceiling against 160 GB needed, and all disk is ephemeral, which loses Postgres and every WAHA session on sleep |

---

_Sources: Hetzner, Netcup, Contabo, Hostinger and DigitalOcean pricing and 2026
price-change coverage; OpenAI, Anthropic, Google, DeepSeek, MiniMax, Moonshot
(Kimi) and Z.ai (GLM) API pricing; ElevenLabs, Deepgram, Cartesia, Speechify,
Groq (Orpheus, PlayAI, Whisper), AssemblyAI, Soniox, Rev AI, Speechmatics, AWS,
Azure and Google Cloud speech pricing; Uplift AI funding and product coverage
(pricing not public); Supabase pricing; Cloudflare Registrar at-cost domains;
WAHA 2026.6 release notes; and reporting on Pakistani card restrictions, PayPal
availability, Hetzner non-EU verification and regional latency. Anthropic rates
are from the first-party pricing table. All checked 2026-09-05._
