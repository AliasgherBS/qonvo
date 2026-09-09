"use client";

import { ArrowDown, ArrowUp, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * Search, filter, sort and paging for the console's tables (finding A5).
 *
 * Neither the tenants list nor Fleet Health had an input of any kind: both
 * rendered every row in whatever order the API returned. Fine at three rows,
 * unusable at two hundred, and two hundred is the point at which an operator
 * most needs to find one tenant.
 *
 * Filtering and sorting happen in the browser rather than on the API. The
 * console's two lists are one row per tenant and one row per session, and Fleet
 * costs a live WAHA call per row, so the page already holds everything and a
 * server round trip per keystroke would buy nothing. The audit log is the
 * opposite shape -- it grows without bound -- and is paged on the server.
 */

export const SELECT_CLASSES =
  "h-9 rounded-xl border border-border-strong bg-surface px-3 text-sm font-semibold " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function SearchBox({
  value,
  onChange,
  placeholder,
  label,
}: {
  value: string;
  onChange: (next: string) => void;
  placeholder: string;
  label: string;
}) {
  return (
    <div className="relative min-w-[14rem] flex-1">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        type="search"
        aria-label={label}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 pl-9"
      />
    </div>
  );
}

export interface SortState<K extends string> {
  key: K;
  direction: "asc" | "desc";
}

/**
 * A clickable column header.
 *
 * The arrow only renders on the active column: an arrow on every header says
 * nothing about which one the table is actually ordered by, which is the one
 * thing the control exists to communicate.
 */
export function SortHeader<K extends string>({
  column,
  label,
  sort,
  onSort,
  className,
}: {
  column: K;
  label: string;
  sort: SortState<K>;
  onSort: (next: SortState<K>) => void;
  className?: string;
}) {
  const active = sort.key === column;
  return (
    // aria-sort belongs on the header cell, not on the button inside it: the
    // column is what is sorted, and the property is not supported on `button`.
    <th
      className={className}
      aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        onClick={() =>
          onSort({
            key: column,
            direction: active && sort.direction === "asc" ? "desc" : "asc",
          })
        }
        className="inline-flex items-center gap-1 font-bold uppercase tracking-wider transition hover:text-foreground"
      >
        {label}
        {active ? (
          sort.direction === "asc" ? (
            <ArrowUp className="h-3 w-3" />
          ) : (
            <ArrowDown className="h-3 w-3" />
          )
        ) : null}
      </button>
    </th>
  );
}

/**
 * Page a list that is already in memory.
 *
 * Resets to the first page whenever the filtered length changes, because
 * otherwise typing a search term while on page four leaves the table blank and
 * looks like no results.
 */
export function usePaging<T>(rows: T[], pageSize = 25) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  const current = Math.min(page, pages - 1);
  const slice = useMemo(
    () => rows.slice(current * pageSize, current * pageSize + pageSize),
    [rows, current, pageSize],
  );

  return {
    slice,
    page: current,
    pages,
    setPage,
    total: rows.length,
    from: rows.length === 0 ? 0 : current * pageSize + 1,
    to: Math.min(rows.length, (current + 1) * pageSize),
  };
}

export function Pager({
  page,
  pages,
  from,
  to,
  total,
  noun,
  onPage,
}: {
  page: number;
  pages: number;
  from: number;
  to: number;
  total: number;
  noun: string;
  onPage: (next: number) => void;
}) {
  if (total === 0) return null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3 text-xs text-muted-foreground">
      <span>
        {from} to {to} of {total} {noun}
      </span>
      {pages > 1 ? (
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page === 0}
            onClick={() => onPage(page - 1)}
          >
            Previous
          </Button>
          <span className="tabular-nums">
            {page + 1} / {pages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= pages - 1}
            onClick={() => onPage(page + 1)}
          >
            Next
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/** Case-insensitive substring match across several fields of one row. */
export function matchesQuery(query: string, ...fields: (string | null | undefined)[]): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return fields.some((field) => (field ?? "").toLowerCase().includes(needle));
}

/** Stable comparator: strings collate, numbers subtract, nulls sort last. */
export function compare(a: unknown, b: unknown): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b));
}
