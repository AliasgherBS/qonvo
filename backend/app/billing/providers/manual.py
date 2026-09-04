"""Admin-driven billing (billing design §2).

The shipped default: no gateway is connected, so an upgrade is a conversation
with the operator, who then records it through the admin subscription endpoint.
This adapter exists so the rest of the system can be finished, tested and used
before a merchant-of-record account exists — and so the seam is proven by a real
second implementation rather than a hypothetical one.
"""

from __future__ import annotations

from app.billing.providers.base import BillingEvent, Checkout


class ManualProvider:
    key = "manual"

    def checkout(self, *, tenant_id: str, plan_key: str) -> Checkout:
        return Checkout(
            instructions=(
                "Reply to this email or message us to move onto the "
                f"{plan_key} plan and we'll switch it over for you."
            )
        )

    def parse_event(self, headers: dict[str, str], raw: bytes) -> BillingEvent | None:
        # Nothing signs manual events; the admin endpoint is the only way in.
        return None


__all__ = ["ManualProvider"]
