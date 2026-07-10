"""``share_payment_details`` skill: give the customer how-to-pay info (§7).

Returns the business's OWN receiving account details (configured in Settings),
verbatim — bank title/number/IBAN, JazzCash/Easypaisa, etc. Never customer card
data. Only offered when the tenant has set ``payment_details``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models.tenant import TenantConfig
from app.skills.registry import SkillContext, SkillDefinition

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {},
}


async def _payment_details(ctx: SkillContext) -> str | None:
    config = ctx.tenant_config
    if config is None:
        config = (
            await ctx.db.execute(
                select(TenantConfig).where(TenantConfig.tenant_id == ctx.tenant_id)
            )
        ).scalar_one_or_none()
    return getattr(config, "payment_details", None)


async def handle(ctx: SkillContext, args: dict[str, Any]) -> dict[str, Any]:
    details = await _payment_details(ctx)
    if not details or not details.strip():
        return {
            "status": "error",
            "message": "Payment details aren't set up — offer to connect them with the team.",
        }
    return {
        "status": "ok",
        "payment_details": details.strip(),
        "message": details.strip(),
    }


DEFINITION = SkillDefinition(
    name="share_payment_details",
    description=(
        "Share the business's payment/account details with a customer who wants "
        "to pay or asks how to pay. Send the details exactly as configured — do "
        "not invent account numbers."
    ),
    parameters=_PARAMETERS,
    handler=handle,
    requires_config_key="payment_details",
)

__all__ = ["DEFINITION", "handle"]
