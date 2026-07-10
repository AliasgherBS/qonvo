"""``take_order`` skill: capture a structured customer order (§7).

Records line items, an optional total, and contact details as an ``orders`` row.
Idempotent via the skill_executions ledger, so a redelivery never double-orders.
No integration required (stored in Postgres); enabled by default.
"""

from __future__ import annotations

from typing import Any

from app.models.business import Order
from app.skills.registry import SkillContext, SkillDefinition

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "description": "The ordered line items.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Item name."},
                    "quantity": {"type": "integer", "description": "How many (default 1)."},
                    "price": {"type": "number", "description": "Unit price, if known."},
                },
                "required": ["name"],
            },
        },
        "customer_name": {"type": "string", "description": "Customer's name, if known."},
        "customer_phone": {
            "type": "string",
            "description": "Customer's phone; defaults to the current chat's number.",
        },
        "currency": {"type": "string", "description": "Currency code/label (e.g. PKR)."},
        "notes": {"type": "string", "description": "Any special instructions."},
    },
    "required": ["items"],
}


def _phone_from_chat_id(chat_id: str | None) -> str | None:
    if not chat_id:
        return None
    return chat_id.split("@", 1)[0] or None


def _normalize_items(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        qty = entry.get("quantity") or 1
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            qty = 1
        price = entry.get("price")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None
        items.append({"name": name, "quantity": qty, "price": price})
    return items


def _compute_total(items: list[dict[str, Any]]) -> float | None:
    # Only meaningful if every line has a price; otherwise leave it for staff.
    if items and all(i["price"] is not None for i in items):
        return round(sum(i["price"] * i["quantity"] for i in items), 2)
    return None


async def handle(ctx: SkillContext, args: dict[str, Any]) -> dict[str, Any]:
    items = _normalize_items(args.get("items"))
    if not items:
        return {"status": "error", "message": "No items to order — nothing was recorded."}

    total = _compute_total(items)
    customer_name = (args.get("customer_name") or "").strip() or None
    customer_phone = (args.get("customer_phone") or "").strip() or _phone_from_chat_id(ctx.chat_id)
    currency = (args.get("currency") or "").strip() or None
    notes = (args.get("notes") or "").strip() or None

    order = Order(
        tenant_id=ctx.tenant_id,
        conversation_id=ctx.conversation_id,
        customer_name=customer_name,
        customer_phone=customer_phone,
        items=items,
        total=total,
        currency=currency,
        status="pending",
        notes=notes,
    )
    ctx.db.add(order)
    await ctx.db.flush()

    summary = ", ".join(f"{i['quantity']}× {i['name']}" for i in items)
    total_str = f" Total: {currency + ' ' if currency else ''}{total}." if total is not None else ""
    return {
        "status": "ordered",
        "order_id": str(order.id),
        "items": items,
        "total": total,
        "message": f"Got it — your order ({summary}) is placed.{total_str} The team will confirm.",
    }


DEFINITION = SkillDefinition(
    name="take_order",
    description=(
        "Record a customer's order once they've decided what they want. Capture "
        "each item with a quantity (and price if you know it from the knowledge "
        "base or a sheet lookup). Confirm the items back to the customer."
    ),
    parameters=_PARAMETERS,
    handler=handle,
)

__all__ = ["DEFINITION", "handle"]
