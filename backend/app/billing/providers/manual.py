"""Admin-driven billing (billing design §2).

The shipped default: no gateway is connected, so an upgrade is a conversation
with the operator, who then records it through the admin subscription endpoint.
This adapter exists so the rest of the system can be finished, tested and used
before a merchant-of-record account exists — and so the seam is proven by a real
second implementation rather than a hypothetical one.
"""

from __future__ import annotations

from app.billing.providers.base import (
    BillingEvent,
    Checkout,
    InvalidWebhookSignature,
    Payment,
)


class ManualProvider:
    key = "manual"

    def checkout(self, *, tenant_id: str, plan_key: str) -> Checkout:
        return Checkout(
            instructions=(
                "Reply to this email or message us to move onto the "
                f"{plan_key} plan and we'll switch it over for you."
            )
        )

    def portal_url(self, *, customer_id: str, return_url: str | None = None) -> str | None:
        # No gateway, so no portal. The billing page falls back to telling the
        # owner to message us, which is what "manual" means.
        return None

    def payments(self, *, customer_id: str, limit: int = 20) -> list[Payment]:
        # An operator recorded the plan by hand; there is no payment ledger to
        # read. Returning [] rather than raising lets the page render the rest.
        return []

    def parse_event(self, headers: dict[str, str], raw: bytes) -> BillingEvent | None:
        # There is no signing scheme, so nothing arriving here can be shown to
        # be authentic. Raising rather than returning None is the honest answer:
        # None now means "verified, not actionable", which this cannot claim.
        raise InvalidWebhookSignature("the manual adapter accepts no webhooks")


__all__ = ["ManualProvider"]
