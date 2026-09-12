# What a tenant actually costs

_Computed 2026-09-12 from production billing data and this repo's own rate
tables. Every per-reply figure below is **measured**, not modelled — the only
estimates are clearly marked._

Provider as configured in production: **OpenAI `gpt-5.4-nano`** for the LLM,
Groq `whisper-large-v3` for speech-in, Groq `orpheus-v1-english` for speech-out.

---

## 0. The number that changes the answer

The working assumption was **~15,000 tokens per query**. Production says
otherwise:

| | Replies | Tokens | Cost | Per reply |
|---|---:|---:|---:|---|
| Text-only days | 24 | 81,335 | $0.024149 | **3,389 tok · $0.001006** |
| Voice days | 10 | 29,616 | $0.037569 | 2,962 tok · $0.003757 |
| **All** | **34** | **110,951** | **$0.061718** | **3,263 tok · $0.001815** |

**3,263 tokens, not 15,000 — the assumption is 4.6× too high**, and every cost
below would have been overstated by roughly that factor.

The reason it is that low is the shape of the prompt, not luck. Retrieval puts
only the matching chunks in front of the model, so a large knowledge base does
not make a reply more expensive; and a WhatsApp reply is short, which keeps the
output side — the expensive side at $0.00125/1K against $0.0002/1K input —
small.

> **Sample size caveat.** 34 replies across five days on one tenant. It agrees
> with the 3,312 tokens/reply in [DEPLOYMENT-AND-COSTS.md](DEPLOYMENT-AND-COSTS.md),
> measured independently on a different conversation, which is the main reason
> to trust it. Re-check it after real traffic.

---

## 1. Cost per plan, if a tenant uses every allowance

| Plan | Messages | LLM | Voice | **AI / month** | Ingestion¹ |
|---|---:|---:|---:|---:|---:|
| Trial | 300 | $0.30 | $0.05 | **$0.35** | $0.01 |
| Starter | 1,000 | $1.01 | $0.05 | **$1.06** | $0.01 |
| Growth | 5,000 | $5.03 | $0.20 | **$5.23** | $0.03 |
| Scale | 20,000 | $20.12 | $1.00 | **$21.12** | $0.08 |

¹ One-off at signup, not monthly, and only if they fill the character cap.
Embeddings are as cheap as everyone says: filling Scale's entire 15 M-character
allowance costs **eight cents**.

**This is the adversarial case** — every message, every voice minute, every
month, forever. A tenant cannot cost more than this without exceeding the plan,
which the quota gate refuses.

## 2. Cost at realistic use

Metered SaaS quotas typically run 20–40% utilised. At **30%**:

| Plan | Messages | LLM | Voice | **AI / month** |
|---|---:|---:|---:|---:|
| Trial | 90 | $0.09 | $0.01 | **$0.11** |
| Starter | 300 | $0.30 | $0.01 | **$0.32** |
| Growth | 1,500 | $1.51 | $0.06 | **$1.57** |
| Scale | 6,000 | $6.04 | $0.30 | **$6.34** |

The 30% is the one genuinely unfounded number here. Your own demo tenant ran
~170 replies in six days, which against Starter's 1,000/month is about 17% —
consistent, but it is one tenant and not a customer.

## 3. Voice, separately

Voice is priced per audio-minute and derived from 172 seconds of real voice
turns: **$0.0100 per audio-minute** on top of the LLM turn it triggers.

That splits roughly into $0.00185/min for transcription and the rest for
speaking the reply back at $22 per million characters. It is small **because
the voice allowances are small** — 5 minutes on Starter, 100 on Scale. Raising
those is the single fastest way to change these economics, and
`compute_tts_cost` already warns that speech-out is "roughly three times the
language model for the same conversation".

**Voice is also English-only** on the configured model. Urdu voice needs a
different, dearer one, which would change this line materially.

---

## 4. What a tenant occupies on the box

Measured figures from [CAPACITY-AND-SCALING.md](CAPACITY-AND-SCALING.md).

| Plan | RAM | Disk after 12 months | CPU / month | Peak-hour cores |
|---|---:|---:|---:|---:|
| Trial | 22 MB | 79 MB | 0.02 h | 0.0001 |
| Starter | 22 MB | 86 MB | 0.05 h | 0.0004 |
| Growth | 22 MB | 244 MB | 0.27 h | 0.0018 |
| Scale | **44 MB** | **816 MB** | 1.07 h | 0.0072 |

RAM is one WAHA session per linked number, so **Scale costs double because it
allows two numbers**. Disk assumes the knowledge caps are actually filled,
which is why Scale is eight times Starter on a four-times message quota.

### How many tenants the box holds

Reserving half the disk for backups and images, and half the cores for latency
headroom:

| Plan | by RAM | by disk | by CPU | **Limit** |
|---|---:|---:|---:|---|
| Trial | 324 | 934 | 18,635 | **324 — RAM** |
| Starter | 324 | 867 | 5,591 | **324 — RAM** |
| Growth | 324 | 304 | 1,118 | **304 — disk** |
| Scale | 162 | 91 | 280 | **91 — disk** |

**CPU is never the constraint, by three orders of magnitude.** The workers
idle-wait on HTTP; they do not compute. Anyone reasoning about this box should
think about memory and disk and ignore cores.

---

## 5. All-in, with the box amortised

The netcup VPS is **$7.20/month**, spread over the tenants each plan allows:

| Plan | Infra / tenant | AI (realistic) | AI (full) | **All-in realistic** | **All-in worst case** |
|---|---:|---:|---:|---:|---:|
| Trial | $0.022 | $0.11 | $0.35 | **$0.13** | **$0.37** |
| Starter | $0.022 | $0.32 | $1.06 | **$0.34** | **$1.08** |
| Growth | $0.024 | $1.57 | $5.23 | **$1.59** | **$5.25** |
| Scale | $0.079 | $6.34 | $21.12 | **$6.42** | **$21.20** |

**Infrastructure is 0.4–6% of cost. The LLM is everything else.** Which means
hosting decisions barely move the economics and model choice moves them
enormously — switching `gpt-5.4-nano` for something ten times dearer multiplies
the whole business's cost of goods by nearly ten.

### What this implies for prices

Prices are not set — the pricing page still says "when prices are settled". For
an 80% gross margin **against the worst case** (not the average), the floor is:

| Plan | Floor at 80% GM on worst case |
|---|---:|
| Trial | — (free) |
| Starter | $5.41 |
| Growth | $26.27 |
| Scale | $106.00 |

Pricing against the worst case rather than the average is the conservative
read, and at these numbers you can afford it: a Starter tenant who uses
*everything* still costs about a dollar.

---

## 6. Where this is soft

- **34 replies, one tenant, five days.** The strongest evidence for it is that
  it agrees with an independent measurement on a different conversation.
- **~22 MB per WAHA session** is derived from two data points, not per-session
  isolation, and it is the number that sets the RAM ceiling — so the tenant
  counts in §4 are the least reliable figures here.
- **30% utilisation is assumed**, not measured. Everything in §2 scales
  linearly with it, so substitute your own number freely.
- **Disk assumes the knowledge caps are filled.** Most tenants will not fill
  them, which makes Scale's 91-tenant limit pessimistic.
- **Nothing here includes** the WhatsApp provider (WAHA is self-hosted and
  free), email (fractions of a cent at this volume), or your time.
