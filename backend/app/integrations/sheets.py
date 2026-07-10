"""Google Sheets client — append rows for ``append_to_sheet`` (DESIGN.md §7)."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SheetsClient(Protocol):
    async def append_row(self, values: list[Any]) -> dict[str, Any]: ...

    async def ping(self) -> None: ...


class GoogleSheetsClient:
    """Adapter over a ``sheets/v4`` service bound to one spreadsheet + tab."""

    def __init__(self, service: Any, spreadsheet_id: str, *, sheet_range: str = "Sheet1") -> None:
        self._service = service
        self._spreadsheet_id = spreadsheet_id
        self._sheet_range = sheet_range

    async def append_row(self, values: list[Any]) -> dict[str, Any]:
        body = {"values": [values]}
        result = await asyncio.to_thread(
            lambda: self._service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self._spreadsheet_id,
                range=self._sheet_range,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body,
            )
            .execute()
        )
        updates = result.get("updates", {})
        return {
            "updated_range": updates.get("updatedRange"),
            "updated_rows": updates.get("updatedRows"),
        }

    async def ping(self) -> None:
        """Confirm the key reaches the spreadsheet AND the target tab exists.

        Metadata-only (no grid data). Validating the tab here means a wrong tab
        name surfaces at Test time with the list of real tabs, instead of a
        cryptic "Unable to parse range" at the first append.
        """
        meta = await asyncio.to_thread(
            lambda: self._service.spreadsheets()
            .get(spreadsheetId=self._spreadsheet_id, includeGridData=False)
            .execute()
        )
        titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
        # A range may be a bare tab ("Leads") or "Tab!A1:D" — the tab is the part
        # before "!". An empty range targets the first tab, which always exists.
        tab = self._sheet_range.split("!", 1)[0].strip().strip("'")
        if tab and titles and tab not in titles:
            raise ValueError(f"Tab '{tab}' not found. Available tabs: {', '.join(titles)}")


__all__ = ["GoogleSheetsClient", "SheetsClient"]
