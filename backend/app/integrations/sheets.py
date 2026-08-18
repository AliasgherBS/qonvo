"""Google Sheets client — append rows for ``append_to_sheet`` (DESIGN.md §7)."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SheetsClient(Protocol):
    async def append_row(self, values: list[Any]) -> dict[str, Any]: ...

    async def read_rows(self) -> list[list[str]]: ...

    async def list_tabs(self) -> list[str]: ...

    async def ping(self) -> None: ...


class GoogleSheetsClient:
    """Adapter over a ``sheets/v4`` service bound to one spreadsheet + tab."""

    def __init__(self, service: Any, spreadsheet_id: str, *, sheet_range: str = "Sheet1") -> None:
        self._service = service
        self._spreadsheet_id = spreadsheet_id
        self._sheet_range = sheet_range

    @property
    def _a1_range(self) -> str:
        """A1 range safe for the Sheets API. A bare tab name with a space (e.g.
        'Qonvo Leads') must be single-quoted or values.get 400s ('Unable to parse
        range'); a range that already has a '!' is assumed pre-formatted."""
        r = self._sheet_range
        if "!" in r:
            return r
        return "'" + r.replace("'", "''") + "'"

    async def append_row(self, values: list[Any]) -> dict[str, Any]:
        body = {"values": [values]}
        result = await asyncio.to_thread(
            lambda: self._service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self._spreadsheet_id,
                range=self._a1_range,
                # RAW, not USER_ENTERED: store values verbatim. USER_ENTERED
                # evaluates leading "+"/"=" as formulas — corrupting phone numbers
                # ("+92..." → a negative number) and, worse, letting a
                # customer-supplied "=IMPORTXML(...)" run (formula injection).
                valueInputOption="RAW",
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

    async def read_rows(self) -> list[list[str]]:
        """All rows in the configured tab (first row is typically the header).

        Backs ``lookup_sheet`` (inventory / order-status / price lookups).
        """
        resp = await asyncio.to_thread(
            lambda: self._service.spreadsheets()
            .values()
            .get(spreadsheetId=self._spreadsheet_id, range=self._a1_range)
            .execute()
        )
        return resp.get("values", [])

    async def list_tabs(self) -> list[str]:
        """Tab titles in this spreadsheet. Metadata-only (no grid data).

        Doubles as the ``drive.file`` access check: under per-file scope this call
        only succeeds for a spreadsheet the owner actually picked, so it is what
        the dashboard uses to populate the tab dropdown after a Picker selection.
        """
        meta = await asyncio.to_thread(
            lambda: self._service.spreadsheets()
            .get(
                spreadsheetId=self._spreadsheet_id,
                includeGridData=False,
                fields="properties.title,sheets.properties.title",
            )
            .execute()
        )
        return [s["properties"]["title"] for s in meta.get("sheets", [])]

    async def ping(self) -> None:
        """Confirm the grant reaches the spreadsheet AND the target tab exists.

        Validating the tab here means a wrong tab name surfaces at Test time with
        the list of real tabs, instead of a cryptic "Unable to parse range" at the
        first append.
        """
        titles = await self.list_tabs()
        # A range may be a bare tab ("Leads") or "Tab!A1:D" — the tab is the part
        # before "!". An empty range targets the first tab, which always exists.
        tab = self._sheet_range.split("!", 1)[0].strip().strip("'")
        if tab and titles and tab not in titles:
            raise ValueError(f"Tab '{tab}' not found. Available tabs: {', '.join(titles)}")


__all__ = ["GoogleSheetsClient", "SheetsClient"]
