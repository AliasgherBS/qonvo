"""Minimal in-process Prometheus metrics (DESIGN.md §12 observability).

Hand-rolled to avoid a new dependency: an HTTP request counter + duration sums,
labelled by method / route-template / status. Route *templates* (``/api/x/{id}``)
are used, not concrete paths, so ids don't blow up label cardinality.
"""

from __future__ import annotations

from collections import defaultdict
from threading import Lock

_lock = Lock()
_request_count: dict[tuple[str, str, str], int] = defaultdict(int)
_duration_sum: dict[tuple[str, str], float] = defaultdict(float)
_duration_count: dict[tuple[str, str], int] = defaultdict(int)


def record_request(method: str, path: str, status: int, duration_s: float) -> None:
    with _lock:
        _request_count[(method, path, str(status))] += 1
        _duration_sum[(method, path)] += duration_s
        _duration_count[(method, path)] += 1


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_prometheus() -> str:
    lines = [
        "# HELP qonvo_http_requests_total Total HTTP requests.",
        "# TYPE qonvo_http_requests_total counter",
    ]
    with _lock:
        for (method, path, status), count in _request_count.items():
            lines.append(
                f'qonvo_http_requests_total{{method="{_escape(method)}",'
                f'path="{_escape(path)}",status="{status}"}} {count}'
            )
        lines += [
            "# HELP qonvo_http_request_duration_seconds Request duration sums.",
            "# TYPE qonvo_http_request_duration_seconds summary",
        ]
        for (method, path), total in _duration_sum.items():
            count = _duration_count[(method, path)]
            label = f'method="{_escape(method)}",path="{_escape(path)}"'
            lines.append(f"qonvo_http_request_duration_seconds_sum{{{label}}} {total}")
            lines.append(f"qonvo_http_request_duration_seconds_count{{{label}}} {count}")
    return "\n".join(lines) + "\n"


__all__ = ["record_request", "render_prometheus"]
