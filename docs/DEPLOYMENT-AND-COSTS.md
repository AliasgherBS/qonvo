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
usual answer. **See §7 before buying — being in Pakistan rules some of these out
in practice, whatever the price says.**

| Provider | Plan | vCPU | RAM | Disk | Monthly | Verdict |
|---|---|---:|---:|---:|---:|---|
| **Netcup** | RS 1000 G12 | 4 **dedicated** | 8 GB DDR5 ECC | 256 GB NVMe | **~€10.74** | Best value on paper: dedicated cores at shared-vCPU money |
| **Contabo** | VPS S | 4 shared | 8 GB | 200 GB | ~$6.99–7.49 | Cheapest, and **the easiest to actually buy from Pakistan** (§7) |
| Hetzner | CX33 | 4 shared | 8 GB | 80 GB | €25.47 | Great network, now expensive, tight disk, **and the hardest to get verified** |
| Hetzner | CX23 | 2 shared | 4 GB | 40 GB | €5.49 | Too small: the Next.js build will not fit |
| Hostinger | KVM 4 | 4 | 16 GB | 200 GB | $12.99 → **$28.99** | Renewal more than doubles |
| DigitalOcean | equivalent | 4 | 8 GB | 160 GB | ~$48 | Convenient, ~4x Netcup |

Whichever you pick: build images on the box, keep the monitoring profile off
until you need it, and stop the staging stack when you are not using it.

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

---

## 6. AI providers, priced model-agnostically

The adapter is one OpenAI-compatible client, so **any of these is a config
change, not a code change**. What you run today (Gemini 2.5 Flash, Groq Whisper,
Groq Orpheus) was chosen for a free tier, not on merit.

### 6.1 The unit that makes these comparable

This deployment measures **~1,000 tokens per reply** — about 900 in, 150 out.
So the cost of **1,000 replies** is `0.9 × input_price + 0.15 × output_price`.
Every LLM row below is priced that way, which is the only fair comparison.

### 6.2 Language models

| Model | $/1M in | $/1M out | **Per 1,000 replies** |
|---|---:|---:|---:|
| Gemini 2.5 Flash-Lite *(retires 16 Oct 2026)* | $0.10 | $0.40 | **$0.15** |
| DeepSeek V4 Flash | $0.14 | $0.28 | **$0.17** |
| Gemini 2.5 Flash *(current)* | $0.15 | $1.25 | **$0.32** |
| GPT-5.6 Luna | $0.20 | $1.20 | **$0.36** |
| MiniMax M2.7 / M3 | $0.30 | $1.20 | **$0.45** |
| DeepSeek V4 Pro | $0.435 | $0.87 | **$0.52** |
| GPT-5 mini | $0.25 | $2.00 | **$0.53** |
| Gemini 3.5 Flash | $0.75 | $4.50 | **$1.35** |
| Claude Haiku 4.5 | $1.00 | $5.00 | **$1.65** |
| Kimi K2.6 | $1.20 | $4.50 | **$1.76** |
| GLM-5.3 (Z.ai) | $1.40 | $4.40 | **$1.92** |
| GPT-5 | $1.25 | $10.00 | **$2.63** |
| Gemini 3.1 Pro | $2.00 | $12.00 | **$3.60** |
| GPT-5.6 Terra | $2.00 | $12.00 | **$3.60** |
| Claude Sonnet 5 | $3.00 | $15.00 | **$4.95** |
| Claude Opus 5 | $5.00 | $25.00 | **$8.25** |
| GPT-5.6 Sol | $5.00 | $30.00 | **$9.00** |
| Claude Fable 5 | $10.00 | $50.00 | **$16.50** |

Qwen3.7 Max is competitive on benchmarks but I could not confirm a current
published rate — treat it as unpriced until you check Alibaba directly.

**The spread is 100x, and quality does not track it linearly.** Five models —
DeepSeek V4 Pro Max, Gemini 3.1 Pro, MiniMax M3, Qwen3.7 Max and Kimi K2.6 —
score within 0.4 points of each other on SWE-bench Verified while their prices
differ by more than 10x. For answering "what time do you close?" from a
retrieved paragraph, **the cheap tier is not a compromise**; that task is
retrieval plus paraphrase, not reasoning.

Practical shortlist for Qonvo: **DeepSeek V4 Flash** ($0.17) if you want the
floor, **Gemini 2.5 Flash** ($0.32) for the status quo, **Claude Haiku 4.5**
($1.65) if instruction-following on the tool loop turns out to matter. At 1,000
messages/month the gap between cheapest and Haiku is **$1.48 per tenant**, which
is noise against a $10 subscription — so choose on reliability, not price.

Prompt caching cuts the input half substantially and Qonvo does not use it yet;
the system prompt and knowledge context are exactly the stable prefix it is for.

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

1,000 messages/month, 10% arriving as voice, voice replies on:

| Configuration | LLM | STT | TTS | **Total** |
|---|---:|---:|---:|---:|
| Floor (DeepSeek Flash + Groq turbo + `tts-1`) | $0.17 | $0.03 | $0.60 | **$0.80** |
| Current (Gemini 2.5 Flash + Groq v3 + Orpheus) | $0.32 | $0.09 | $0.88 | **$1.29** |
| Urdu-capable (Gemini Flash + turbo + ElevenLabs Flash) | $0.32 | $0.03 | $2.00 | **$2.35** |
| Premium (Claude Haiku + turbo + ElevenLabs v3) | $1.65 | $0.03 | $4.00 | **$5.68** |
| Text only, floor | $0.17 | — | — | **$0.17** |

**Voice dominates every row.** In the current configuration TTS is 68% of the
bill; in the premium row it is 70%. The LLM is not where your money goes, and
`voice_reply_mode` is the biggest cost lever you have.

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
| Email (Gmail SMTP) | $0, capped at 500/day |
| Monitoring (self-hosted) | $0 |
| **Fixed total** | **~$12/month** |
| AI, per tenant | +$0.17 text-only floor / +$1.29 current / +$2.35 Urdu-capable voice |

Priced with the Urdu-capable voice stack ($2.35/tenant), the realistic
configuration for this market:

| Tenants | Fixed | AI | Total | Revenue at $10/tenant | Margin |
|---:|---:|---:|---:|---:|---:|
| 5 | $12 | $12 | **$24** | $50 | 52% |
| 20 | $12 | $47 | **$59** | $200 | 71% |
| 50 | $12 | $118 | **$130** | $500 | 74% |
| 100 | $24 (bigger box) | $235 | **$259** | $1,000 | 74% |

Text-only tenants cost a seventh of that, so the mix matters more than the tier.

The economics work because WAHA has no per-message fee and Gemini Flash is
nearly free per turn. **Payment processing will take a bigger cut than your
infrastructure** — a merchant of record charges roughly 5%, which at 100 tenants
is $50/month against $159 of infrastructure.

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
| VPS | **Contabo** to start (buyable from Pakistan); Netcup if payment clears |
| Domain | Check `qonvo.com` first; otherwise `qonvo.org` at Cloudflare |
| LLM | Any cheap-tier model works; pick on reliability. $1.48/tenant separates cheapest from Claude Haiku |
| STT | Move to `whisper-large-v3-turbo`, same key, ~64% cheaper |
| Database | Self-hosted; get backups offsite this month |
| Price table | Correct Gemini to $0.15/$1.25 |
| Payments in | Confirm a merchant of record actually pays out to Pakistan **before** building on it |
| Load test | Do one before promising concurrency |

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
