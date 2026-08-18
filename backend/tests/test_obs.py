"""Redis-backed business metrics (app.core.obs) — no live Redis needed."""

from __future__ import annotations

from app.core import obs


class _FakeRedis:
    """Minimal in-memory stand-in for the hash ops obs uses."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, float]] = {}

    async def hincrbyfloat(self, key: str, field: str, value: float) -> float:
        self.hashes.setdefault(key, {})[field] = self.hashes.get(key, {}).get(field, 0) + value
        return self.hashes[key][field]

    async def hincrby(self, key: str, field: str, value: int) -> int:
        return await self.hincrbyfloat(key, field, value)

    async def hgetall(self, key: str) -> dict[str, str]:
        return {k: str(v) for k, v in self.hashes.get(key, {}).items()}

    def pipeline(self, transaction: bool = False):  # noqa: FBT001,FBT002
        outer = self

        class _Pipe:
            def __init__(self) -> None:
                self.ops: list = []

            def hincrbyfloat(self, key, field, value):
                self.ops.append((key, field, value))

            def hincrby(self, key, field, value):
                self.ops.append((key, field, value))

            async def execute(self):
                for key, field, value in self.ops:
                    await outer.hincrbyfloat(key, field, value)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        return _Pipe()


def test_fieldset_sorted_and_escaped():
    assert obs._fieldset(None) == ""
    assert obs._fieldset({"b": "2", "a": "1"}) == 'a="1",b="2"'
    assert obs._fieldset({"gate": 'we"ird'}) == 'gate="we\\"ird"'


async def test_incr_and_render(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(obs, "get_redis", lambda: fake)
    await obs.incr("qonvo_replies_sent_total")
    await obs.incr("qonvo_pipeline_gate_total", {"gate": "rate_limited"})
    await obs.incr("qonvo_llm_cost_usd_total", value=0.0025)
    out = await obs.render()
    assert "# TYPE qonvo_replies_sent_total counter" in out
    assert "qonvo_replies_sent_total 1" in out
    assert 'qonvo_pipeline_gate_total{gate="rate_limited"} 1' in out
    assert "qonvo_llm_cost_usd_total 0.0025" in out


async def test_observe_histogram(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(obs, "get_redis", lambda: fake)
    await obs.observe("qonvo_pipeline_duration_seconds", 1.5)
    out = await obs.render()
    assert "# TYPE qonvo_pipeline_duration_seconds histogram" in out
    assert 'qonvo_pipeline_duration_seconds_bucket{le="2.0"} 1' in out
    assert 'qonvo_pipeline_duration_seconds_bucket{le="0.5"} 0' in out
    assert "qonvo_pipeline_duration_seconds_count 1" in out


async def test_incr_never_raises_when_redis_down(monkeypatch):
    class _Broken:
        async def hincrbyfloat(self, *a):
            raise ConnectionError("redis down")

    monkeypatch.setattr(obs, "get_redis", lambda: _Broken())
    # Must swallow — a metrics hiccup can't break a reply.
    await obs.incr("qonvo_replies_sent_total")


async def test_snapshot_rolls_up(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(obs, "get_redis", lambda: fake)
    await obs.incr("qonvo_replies_sent_total", value=3)
    await obs.observe("qonvo_pipeline_duration_seconds", 2.0)
    snap = await obs.snapshot()
    assert snap["counters"]["qonvo_replies_sent_total"]["_"] == 3.0
    assert snap["histograms"]["qonvo_pipeline_duration_seconds"]["count"] == 1
