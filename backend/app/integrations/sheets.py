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
        """Verify the key can reach the spreadsheet (metadata read, no grid data)."""
        await asyncio.to_thread(
            lambda: self._service.spreadsheets()
            .get(spreadsheetId=self._spreadsheet_id, includeGridData=False)
            .execute()
        )


__all__ = ["GoogleSheetsClient", "SheetsClient"]
