# Capacity, scaling and the work it implies

_Load-tested 2026-09-09 against staging with the LLM, embedding and WAHA
endpoints stubbed at their measured real latencies, so the run cost $0 and
production was never touched. Supersedes the line in
[DEPLOYMENT-AND-COSTS.md](DEPLOYMENT-AND-COSTS.md) that said load behaviour was
untested._

Target host: the netcup VPS — **4 vCPU, 8 GB RAM, ~145 GB usable** after the
system, Docker images and editor/agent tooling.

---

## 0. The verdict

**~50–70 paying tenants as shipped. ~150–200 after a day of tuning.**

CPU and disk are nowhere near binding. The ceiling is **a concurrency limit
nobody set, then WAHA's per-session RAM**. At three times the current
throughput ceiling the box uses 0.85 of its 4 cores — the workers are
idle-waiting on HTTP, not computing.

That is the single most important fact here: **you are not CPU-bound, you are
concurrency-limited by a default in a dependency** (see P1).

---

## 1. What was measured

| | Result |
|---|---|
| Sustained throughput, default config (1 worker, `max_jobs=10`) | **1.4 replies/s** = 84/min = 5,000/hr |
| Same, 4 worker replicas (40 slots) | **4.4 replies/s** = 264/min = 15,800/hr |
| CPU at 4.4 replies/s | **0.85 cores** (worker 62%, postgres 12%, redis 11%, api 1%) |
| Mean pipeline duration under load | 7.3 s (production real-LLM metric: 8.6 s) |
| Webhook ingress ceiling | ~130 req/s, flat from 25→200 concurrency, single uvicorn process |
| RAG query, 1,000 chunks/tenant, 100k total | 20 ms, 16,063 buffers = **125 MB touched per query** |
| pgvector storage | **8.1 KB/chunk** measured at 100k rows (814 MB) |
| Production idle footprint | ~865 MB, +300 MB with monitoring |

Throughput is exactly `10 slots ÷ 7.2 s`. The arithmetic is the whole story.

### Capacity translated to tenants

Assuming peak hour ≈ 20% of daily volume, held at 50% utilisation for latency
headroom → **~12,600 replies/day on defaults**.

| Tenant profile | Replies/day | Default config | 4 workers |
|---|---|---|---|
| Light (20 convs × 4 turns) | 80 | ~155 | RAM-bound |
| Typical (40 convs × 5 turns) | 200 | **~63** | **~195** |
| Heavy (near the 500/day cap) | 500 | ~25 | ~78 |

**RAM at 150 sessions:** 1.2 GB baseline + 150 × 22 MB WAHA ≈ **4.5 GB of 8 GB**.
**Disk after 12 months at that scale:** ~82 GB of 145 GB, half of it backups.

Two ceilings are **product, not hardware**: the per-session token bucket caps a
single tenant at ~11–20 replies/min, and `daily_cap` at 500/day.

---

## 2. The work, in priority order

### P1 — the 10-slot concurrency limit is invisible

The single thing between the current config and 3× throughput — and it is
**not hard-coded, it is unset**. `WorkerSettings`
([`worker.py:410`](../backend/app/workers/worker.py)) declares `functions`,
`on_startup`, `on_shutdown`, `max_tries` and `redis_settings`, and nothing
else. `max_jobs` defaults to **10 inside arq**.

That is worse than a constant would be: grepping the codebase for `max_jobs`
returns nothing, so the natural conclusion is that no limit exists. The
throughput ceiling of this product is currently a number in a dependency's
source.

Set it explicitly and make it env-driven, with the default left at 10 so
nothing shifts under anyone. The value of the change is as much that the limit
becomes *visible* as that it becomes tunable.

**Do not raise it without P2.** More slots means more concurrent database
sessions, and the pool maths below is already tight.

### P2 — Postgres runs out of connections before it runs out of CPU

[`session.py:16`](../backend/app/db/session.py) creates **two** engines with
SQLAlchemy defaults (`pool_size=5`, `max_overflow=10` each). api + worker +
scheduler = **90 potential connections against `max_connections=100`**. One
extra worker replica takes it to 120 and the box starts refusing connections
under load — as a burst of `TooManyConnections`, not a graceful slowdown.

Set explicit pool sizes per process and raise `max_connections`. This is a
prerequisite for P1, not a follow-up to it.

### P3 — `shared_buffers` is smaller than one query's working set

Default **128 MB**, while a single RAG query touches a measured **125 MB**. Every
concurrent query is fighting for the whole buffer pool. At 8 GB:
`shared_buffers=2GB`, `effective_cache_size=5GB`.

### P4 — Health checks report green during a total outage

**Found live on 2026-09-09**, not in the load test. With all outbound TCP
blocked at the network firewall — WAHA unable to reach WhatsApp, the LLM
unreachable, the bot completely silent — `/readyz` still returned:

```json
{"status":"ok","checks":{"database":"ok","redis":"ok","waha":"ok"}}
```

`waha: ok` means *the API can reach the WAHA container*. It says nothing about
whether WAHA can reach WhatsApp, or whether the LLM provider is reachable. A
readiness probe that cannot distinguish "healthy" from "totally non-functional"
is worse than none, because it will be trusted.

Readiness should assert the things whose absence means no reply can be
produced: WAHA session state is `WORKING`, and the configured LLM endpoint is
reachable. Both need caching and a short timeout so the probe itself does not
become load.

### P5 — Build cache grows without bound

No `docker builder prune` anywhere. **19.6 GB** on the dev box, uncapped,
growing with every `qonvo-redeploy.sh`. On a 145 GB VPS that is a slow-motion
disk-full outage. Cap it (`--filter keep-storage`) in the deploy path.

### P6 — No retention on `messages` or `analytics_events`

They only grow, and they drive both database size and all seven backup copies.
Nothing reads a two-year-old debounce-era message. Needs a retention policy and
a scheduled prune, decided as a product question (what does a tenant get to
keep?) rather than an ops one.

### P7 — MinIO runs and nothing uses it

No MinIO client is constructed anywhere. The only references are settings
fields, a comment in the SSRF guard listing container names, and
[`knowledge.py:350`](../backend/app/api/knowledge.py), which says outright:
*"Falls back to a local volume path — there is no MinIO client wired up yet."*
Confirmed independently during the VPS migration: the volume held **15 KB**,
while real knowledge uploads live on the `knowledge_data` volume at
`/data/knowledge`. It costs
94 MB RAM and a 241 MB image to run a service with no callers. Remove it from
the compose file, or document what it is being kept for.

### P8 — No `mem_limit` on any application service

The monitoring services have limits; `api`, `worker` and `waha` do not. One
leak takes the whole box down rather than one container. Given WAHA's
per-session memory is the RAM ceiling, it is the one that most needs a bound.

### P9 — Don't run the staging stack on the production VPS

~640 MB plus a duplicate 4.1 GB WAHA image. Staging belongs on the dev machine
behind the Cloudflare Tunnel (see
[GOING-LIVE-ON-A-DOMAIN.md §10](GOING-LIVE-ON-A-DOMAIN.md)), which is free and
cannot contend with production for RAM.

---

## 3. What is still unmeasured

Stated plainly, because the value of the numbers above depends on knowing where
they stop.

- **~22 MB/session for WAHA is the weakest number in the model, and it sets the
  RAM ceiling.** It is derived from two data points, not per-session isolation.
  Everything else in §1 was measured directly. Measure it properly before
  planning past ~100 tenants.
- **The stub replaced the LLM's latency, not WAHA's Signal-protocol crypto.**
  Real sessions do cryptographic work the load test never exercised. The
  migration made this concrete: a freshly linked NOWEB session uploaded **812
  pre-keys** and churned through repeated app-state sync failures before
  settling.
- **The Next.js build peaks at 1.5–2.5 GB.** On 8 GB with the stack running that
  fits, but only build on the box when nothing else is spiking. This is an
  argument for building images in CI once deploys are automated.
- **Nothing here tested failure modes** — provider outage, WAHA disconnect,
  Postgres restart under load. The 2026-09-09 firewall incident was an
  accidental, and instructive, first sample.

---

## 4. Suggested sequence

P2 before P1, because raising concurrency onto an already-tight connection pool
converts a throughput win into an outage. P4 next, since without it you cannot
see whether any of the rest worked. Then P3. P5–P9 are independent and can be
picked up in any order.

```
P2 (pools)  →  P1 (max_jobs)  →  P4 (real health checks)  →  P3 (shared_buffers)
P5 · P6 · P7 · P8 · P9 — independent
```
