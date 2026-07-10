"""``lookup_sheet`` skill: search the connected Google Sheet (§7).

Powers live lookups — inventory, prices, order status — from the tenant's sheet.
The first row is treated as the header; matching rows are returned as
column→value objects. Read-only; requires the ``google_sheets`` integration.
"""

from __future__ import annotations

from typing import Any

from app.integrations import GOOGLE_SHEETS
from app.integrations.resolver import resolve_integration_client
from app.skills.registry import SkillContext, SkillDefinition

_DEFAULT_MAX = 5

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Text to search across all columns (a product name or order id).",
        },
        "max_results": {
            "type": "integer",
            "description": f"Max rows to return (default {_DEFAULT_MAX}).",
        },
    },
    "required": ["query"],
}


def _match(rows: list[list[str]], query: str, limit: int) -> list[dict[str, str]]:
    if not rows:
        return []
    header = [str(h) for h in rows[0]]
    needle = query.lower()
    matches: list[dict[str, str]] = []
    for row in rows[1:]:
        if any(needle in str(cell).lower() for cell in row):
            matches.append(
                {
                    (header[i] if i < len(header) else f"col{i}"): str(v)
                    for i, v in enumerate(row)
                }
            )
            if len(matches) >= limit:
                break
    return matches


async def handle(ctx: SkillContext, args: dict[str, Any]) -> dict[str, Any]:
    client = await resolve_integration_client(ctx, GOOGLE_SHEETS)
    if client is None:
        return {"status": "error", "message": "The spreadsheet isn't connected yet."}

    query = (args.get("query") or "").strip()
    if not query:
        return {"status": "error", "message": "Nothing to look up — no query was given."}
    limit = int(args.get("max_results") or _DEFAULT_MAX)

    rows = await client.read_rows()
    matches = _match(rows, query, limit)
    return {
        "status": "ok",
        "query": query,
        "matches": matches,
        "count": len(matches),
        "message": (
            f"Found {len(matches)} row(s) matching '{query}'."
            if matches
            else f"No rows matched '{query}'."
        ),
    }


DEFINITION = SkillDefinition(
    name="lookup_sheet",
    description=(
        "Look something up in the business's spreadsheet — stock/inventory, "
        "prices, or an order's status. Search by product name, order id, or any "
        "keyword. Only report what the sheet actually contains."
    ),
    parameters=_PARAMETERS,
    handler=handle,
    requires_integration=GOOGLE_SHEETS,
)

__all__ = ["DEFINITION", "handle"]
