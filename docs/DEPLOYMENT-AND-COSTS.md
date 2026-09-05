# Qonvo deployment, sizing and costs

_Measured on this machine on 2026-09-05, priced against rates checked the same
day. Every resource number below is observed, not estimated, unless it says
otherwise._

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

### 2.1 WhatsApp session files, measured per session

| Session | Files | Disk | What it is |
|---|---:|---:|---|
| `ali-toys` | 5,511 | **24 MB** | 4,678 lid-mapping files + 810 pre-keys |
| `test_001` | 926 | 4.2 MB | active, smaller address book |
| `try-…` | 817 | 3.4 MB | |
| never-linked | 1 | 124 KB | |

The dominant cost is **not** message history, it is thousands of tiny JSON files
each occupying a 4 KB filesystem block. 4,678 lid-mapping files hold maybe 200
bytes apiece and consume ~19 MB.

**`fullSync` is now off by default**, which is what created those mappings by
walking the whole address book on connect. New sessions should settle at roughly
**3–4 MB** (creds, ~810 pre-keys, a small store) **plus ~4 KB per distinct
contact actually messaged**.

| Tenant profile | Session disk |
|---|---:|
| Quiet (few hundred contacts) | ~4–5 MB |
| Busy (2,500 contacts) | ~14 MB |
| Very busy (10,000 contacts) | ~44 MB |

### 2.2 Postgres, measured

Whole database today: **12 MB** across 4 tenants. Per-row costs at current
volumes (index overhead included, so these are pessimistic and amortise down):

| Table | Measured | Steady-state estimate |
|---|---:|---|
| `messages` | 2.3 KB/row at 50 rows | ~0.5–1 KB/message |
| `knowledge_chunks` | 112 KB at 1 row | ~6–8 KB/chunk (a 1536-dim vector is 6.1 KB) |

**Per tenant, per month**, for a business handling 1,000 customer messages:

| Item | Size |
|---|---:|
| 2,000 messages (in + out) | ~2 MB |
| Knowledge base, 100 chunks | ~0.7 MB, one-off |
| Session files | ~4 MB, one-off, grows with contacts |
| **First month** | **~7 MB** |
| **Each month after** | **~2 MB** |

**100 tenants ≈ 700 MB in year one.** Storage is not your constraint; it is
nowhere close.

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
usual answer.

| Provider | Plan | vCPU | RAM | Disk | Monthly | Verdict |
|---|---|---:|---:|---:|---:|---|
| **Netcup** | RS 1000 G12 | 4 **dedicated** | 8 GB DDR5 ECC | 256 GB NVMe | **~€10.74** | **Recommended.** Dedicated cores and ECC at shared-vCPU money |
| Contabo | VPS S | 4 shared | 8 GB | 200 GB | ~$6.99–7.49 | Cheapest. Known for variable I/O and support |
| Hetzner | CX33 | 4 shared | 8 GB | 80 GB | €25.47 | Excellent network, now expensive; disk is tight |
| Hetzner | CX23 | 2 shared | 4 GB | 40 GB | €5.49 | Too small: the Next.js build will not fit |
| Hostinger | KVM 4 | 4 | 16 GB | 200 GB | $12.99 → **$28.99** | Renewal more than doubles. Read the small print |
| DigitalOcean | equivalent | 4 | 8 GB | 160 GB | ~$48 | Convenient, ~4x the price of Netcup |

**Recommendation: Netcup RS 1000 G12.** Dedicated cores matter here because the
Next.js build and the pgvector queries are the two things that actually contend
for CPU, and 256 GB of NVMe removes the disk question entirely. Contabo is the
answer only if the last few dollars matter more than predictable performance.

Whichever you pick: build the images on the box (you have the cores), keep the
monitoring profile off until you need it, and put the staging stack behind a
`docker compose stop` when you are not using it.

---

## 5. The domain

`qonvo.org` is fine and it is consistent with what is already configured. Two
things worth knowing before you commit:

- **Check `qonvo.com` first.** It did not resolve when probed, which hints it may
  be free. For a commercial product `.com` is materially better: `.org` reads as
  non-profit to a business buyer, and you will be saying the domain out loud to
  Pakistani business owners who will assume `.com` by default.
- Register wherever renewal equals registration. **Cloudflare Registrar sells
  `.org` at cost, about $8.50/year, with no renewal jump and free WHOIS
  privacy.** Porkbun prices the same way. Namecheap and GoDaddy discount year one
  and recover it later.

Changing the domain touches four coupled places at once: `AUTH_URL`,
`QONVO_GOOGLE_OAUTH_REDIRECT_BASE`, `QONVO_DASHBOARD_BASE_URL`, and the redirect
URIs in the Google Cloud console. Change one, change all four.

---

## 6. AI provider costs

Grounded in **measured** usage from this deployment: 24 replies consumed 24,099
tokens, so about **1,000 tokens per reply** (roughly 900 in, 150 out with the
2,000-token RAG budget and the rolling summary).

Rates as of 2026-09-05:

| Service | Model in use | Rate |
|---|---|---|
| LLM | Gemini 2.5 Flash | $0.15 / 1M input, $1.25 / 1M output |
| Embeddings | gemini-embedding-001 | $0.15 / 1M input |
| STT | Groq whisper-large-v3 | ~$0.11 / hour of audio (turbo is $0.04) |
| TTS | Groq Orpheus English | **$22 / 1M characters** |
| TTS alternative | OpenAI tts-1 | $15 / 1M characters |

### Cost per tenant per month

A business handling **1,000 customer messages/month**:

| Item | Assumption | Cost |
|---|---|---:|
| LLM | 1,000 replies × (900 in + 150 out) | **$0.32** |
| Embeddings | 1,000 query embeddings + one-off ingest | $0.02 |
| **Text only** | | **~$0.35** |
| STT | 10% arrive as voice, 30s each (50 min) | $0.09 |
| TTS | 100 voice replies × 400 chars | $0.88 |
| **With voice** | | **~$1.30** |

At 10,000 messages/month the text cost is ~$3.40 and the voice-heavy cost around
$13.

### Two observations that matter more than the totals

**Voice is your expensive feature, not the model.** TTS at $22/1M characters
costs roughly **three times the LLM** for the same conversation. If margins ever
tighten, `voice_reply_mode` is the lever, and switching to OpenAI `tts-1` at
$15/1M saves ~30% immediately.

**Your price table is 2× the real rate.** `config.py` prices Gemini 2.5 Flash at
$0.30/$2.50 per million, which was the OpenRouter rate; Google direct is now
$0.15/$1.25. You are over-reporting AI cost by half, which is the safe direction
but makes margins look worse than they are.

Also note **Gemini 2.5 Flash-Lite retires on 16 October 2026**. You are not on
it, but it is a reminder that a pinned model is a dependency with an expiry date.

---

## 7. Postgres: keep it in-house, for now

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

## 8. Total cost of ownership

| Line | Monthly |
|---|---:|
| VPS (Netcup RS 1000 G12) | ~$12 |
| Domain (.org at cost, amortised) | $0.71 |
| Offsite backup (optional, recommended) | ~$4 |
| WAHA | **$0** — everything moved into the free Core in 2026.6.1, no session limit |
| Email (Gmail SMTP) | $0, capped at 500/day |
| Monitoring (self-hosted) | $0 |
| **Fixed total** | **~$17/month** |
| AI, per tenant | +$0.35 text / +$1.30 with voice |

| Tenants | Fixed | AI | Total | Revenue at $10/tenant | Margin |
|---:|---:|---:|---:|---:|---:|
| 5 | $17 | $7 | **$24** | $50 | 52% |
| 20 | $17 | $26 | **$43** | $200 | 79% |
| 50 | $17 | $65 | **$82** | $500 | 84% |
| 100 | $29 (bigger box) | $130 | **$159** | $1,000 | 84% |

The economics work because WAHA has no per-message fee and Gemini Flash is
nearly free per turn. **Payment processing will take a bigger cut than your
infrastructure** — a merchant of record charges roughly 5%, which at 100 tenants
is $50/month against $159 of infrastructure.

---

## 9. Scaling path

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

## 10. Open decisions

| Decision | Recommendation |
|---|---|
| VPS | Netcup RS 1000 G12 |
| Domain | Check `qonvo.com` first; otherwise `qonvo.org` at Cloudflare |
| Database | Self-hosted; add offsite backups this month |
| TTS | Switch to OpenAI `tts-1` for a 30% saving, or keep Orpheus for quality |
| Price table | Correct Gemini to $0.15/$1.25 so margins are accurate |
| Load test | Do one before promising concurrency to anybody |

---

_Sources: Hetzner and Netcup pricing pages and 2026 price-change coverage,
Contabo and Hostinger pricing reviews, Google Gemini API pricing, Groq pricing
(Whisper and Orpheus), OpenAI TTS pricing, Supabase pricing, Cloudflare Registrar
at-cost domain pricing, and the WAHA 2026.6 release notes making all features
free. All checked 2026-09-05._
