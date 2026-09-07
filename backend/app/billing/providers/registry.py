"""Resolve the configured billing provider (billing design §3.4)."""

from __future__ import annotations

from app.billing.providers.base import BillingProvider
from app.billing.providers.manual import ManualProvider
from app.billing.providers.polar import PolarProvider
from app.core.config import settings


class UnknownBillingProvider(RuntimeError):
    """Configured provider has no adapter.

    Deliberately loud: silently falling back to ``manual`` would look like a
    working system that has quietly stopped taking money.
    """


_PROVIDERS: dict[str, type] = {
    ManualProvider.key: ManualProvider,
    PolarProvider.key: PolarProvider,
}


def resolve_billing_provider(key: str | None = None) -> BillingProvider:
    name = key or settings.billing_provider
    adapter = _PROVIDERS.get(name)
    if adapter is None:
        raise UnknownBillingProvider(f"no billing adapter for {name!r}")
    return adapter()


__all__ = ["UnknownBillingProvider", "resolve_billing_provider"]
