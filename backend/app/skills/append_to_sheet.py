"""``append_to_sheet`` skill: append a row to the tenant's Google Sheet (§7).

Requires the ``google_sheets`` integration. The model supplies a ``fields``
object; the handler appends its values (in the order given) as one row. Keeping
field keys consistent across turns keeps the sheet's columns aligned — the skill
description instructs the model accordingly.
"""

from __future__ import annotations

from typing import Any

from app.integrations import GOOGLE_SHEETS
from app.integrations.resolver import resolve_integration_client
from app.skills.registry import SkillContext, SkillDefinition

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "object",
            "description": (
                "Column name → value for this row (e.g. {'name': 'Ali', "
                "'phone': '+92300', 'request': 'wants a quote'}). Use the same "
                "keys in the same order every time so the columns stay aligned."
            ),
            "additionalProperties": {"type": "string"},
        },
    },
    "required": ["fields"],
}


async def handle(ctx: SkillContext, args: dict[str, Any]) -> dict[str, Any]:
    client = await resolve_integration_client(ctx, GOOGLE_SHEETS)
    if client is None:
        return {"status": "error", "message": "The spreadsheet isn't connected yet."}

    fields = args.get("fields")
    if not isinstance(fields, dict) or not fields:
        return {"status": "error", "message": "Nothing to record — no fields were provided."}

    row = [str(value) if value is not None else "" for value in fields.values()]
    result = await client.append_row(row)

    return {
        "status": "recorded",
        "updated_range": result.get("updated_range"),
        "message": "Saved to the sheet.",
    }


DEFINITION = SkillDefinition(
    name="append_to_sheet",
    description=(
        "Append a row to the business's Google Sheet — use it to log leads, "
        "orders, or requests the business wants captured in their spreadsheet."
    ),
    parameters=_PARAMETERS,
    handler=handle,
    requires_integration=GOOGLE_SHEETS,
)

__all__ = ["DEFINITION", "handle"]
