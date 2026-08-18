"""Cross-process business/pipeline metrics, backed by Redis (DESIGN.md §12).

The AI pipeline runs in the arq **worker**, which has no HTTP server — so it can't
expose ``/metrics`` itself. Instead every process (api + worker) records business
metrics into shared Redis, and the API's ``/metrics`` endpoint renders them
alongside its own in-process HTTP metrics. One scrape target, no extra processes —
the right shape for a single small VPS.

Storage (all under ``qonvo:m:``):
- counters  → hash ``qonvo:m:c:{name}``  field=label-set  value=float (HINCRBYFLOAT)
- histogram → hash ``qonvo:m:h:{name}``  fields sum/count/le:<b> (HINCRBY/FLOAT)

Recording never raises into the caller — a metrics hiccup must not break a reply.
"""

from __future__ import annotations

from app.core.logging import logger
from app.core.redis import get_redis

# name → (prom type, HELP). Only registered names get HELP/TYPE headers; recording
# an unknown name still works but renders bare.
_COUNTERS: dict[str, str] = {
    "qonvo_messages_processed_total": "Inbound message fragments processed.",
    "qonvo_replies_sent_total": "Outbound replies sent to customers.",
    "qonvo_pipeline_gate_total": "Turns short-circuited by a gate, by reason.",
    "qonvo_llm_cost_usd_total": "Cumulative LLM spend in USD.",
    "qonvo_llm_tokens_total": "Cumulative LLM tokens (prompt+completion).",
    "qonvo_voice_seconds_total": "Cumulative metered voice seconds (in+out).",
    "qonvo_provider_errors_total": "LLM/STT/TTS provider call failures, by kind.",
    "qonvo_whatsapp_send_failures_total": "Failed outbound WhatsApp sends.",
    "qonvo_webhook_unauthorized_total": "Webhook deliveries rejected (bad HMAC).",
    "qonvo_job_failures_total": "Worker jobs that exhausted retries.",
    "qonvo_skill_invocations_total": "Agent skill/tool invocations, by name+outcome.",
}
_HISTOGRAMS: dict[str, str] = {
    "qonvo_pipeline_duration_seconds": "End-to-end pipeline turn latency.",
}
_BUCKETS = (0.5, 1.0, 2.0, 5.0, 10.0, 30.0)


def _escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"')


def _fieldset(labels: dict[str, str] | None) -> str:
    if not labels:
        return ""
    return ",".join(f'{k}="{_escape(str(v))}"' for k, v in sorted(labels.items()))


async def incr(name: str, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
    """Increment a counter by ``value`` (default 1). Fire-and-forget, never raises."""
    try:
        await get_redis().hincrbyfloat(f"qonvo:m:c:{name}", _fieldset(labels), value)
    except Exception as exc:  # noqa: BLE001 — metrics must never break a request
        logger.debug(f"metric incr failed ({name}): {exc}")


async def observe(name: str, seconds: float) -> None:
    """Record one observation into a histogram (sum/count/buckets). Never raises."""
    try:
        r = get_redis()
        key = f"qonvo:m:h:{name}"
        async with r.pipeline(transaction=False) as pipe:
            pipe.hincrbyfloat(key, "sum", seconds)
            pipe.hincrby(key, "count", 1)
            for b in _BUCKETS:
                if seconds <= b:
                    pipe.hincrby(key, f"le:{b}", 1)
            pipe.hincrby(key, "le:+Inf", 1)
            await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"metric observe failed ({name}): {exc}")


async def render() -> str:
    """Render all Redis-backed metrics in Prometheus text format."""
    r = get_redis()
    lines: list[str] = []
    try:
        for name, help_text in _COUNTERS.items():
            data = await r.hgetall(f"qonvo:m:c:{name}")
            if not data:
                continue
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} counter")
            for fields, value in data.items():
                suffix = f"{{{fields}}}" if fields else ""
                lines.append(f"{name}{suffix} {value}")
        for name, help_text in _HISTOGRAMS.items():
            data = await r.hgetall(f"qonvo:m:h:{name}")
            if not data:
                continue
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} histogram")
            for b in (*_BUCKETS, "+Inf"):
                v = data.get(f"le:{b}", "0")
                lines.append(f'{name}_bucket{{le="{b}"}} {v}')
            lines.append(f"{name}_sum {data.get('sum', '0')}")
            lines.append(f"{name}_count {data.get('count', '0')}")
    except Exception as exc:  # noqa: BLE001 — a scrape must not 500
        logger.warning(f"metrics render failed: {exc}")
    return "\n".join(lines) + ("\n" if lines else "")


async def snapshot() -> dict:
    """Structured rollup for the admin System Health page (not Prometheus)."""
    r = get_redis()
    out: dict = {"counters": {}, "histograms": {}}
    try:
        for name in _COUNTERS:
            data = await r.hgetall(f"qonvo:m:c:{name}")
            if data:
                out["counters"][name] = {k or "_": float(v) for k, v in data.items()}
        for name in _HISTOGRAMS:
            data = await r.hgetall(f"qonvo:m:h:{name}")
            if data:
                total = float(data.get("sum", 0))
                count = int(float(data.get("count", 0)))
                out["histograms"][name] = {
                    "count": count,
                    "avg": round(total / count, 3) if count else 0.0,
                }
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"metrics snapshot failed: {exc}")
    return out


__all__ = ["incr", "observe", "render", "snapshot"]
