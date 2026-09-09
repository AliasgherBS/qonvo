"use client";

import { Radio } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { SessionControl } from "@/components/admin/session-control";
import {
  compare,
  matchesQuery,
  Pager,
  SearchBox,
  SELECT_CLASSES,
  SortHeader,
  usePaging,
  type SortState,
} from "@/components/admin/table-controls";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { adminFleet, type FleetSession, type SessionStatus } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * Fleet health.
 *
 * Two findings land here.
 *
 * A1 is the row's controls, and it lives in `SessionControl`: four equal
 * buttons, one of which unlinks a customer's phone.
 *
 * A5 is the shape of the list. It rendered every session in whatever order the
 * API returned, with no search and no filter, on the one screen where the
 * question is always "which one is broken". So **failed sessions sort first by
 * default** -- the ordering does the noticing rather than the operator -- and
 * the row itself is tinted, because the report is right that this is the screen
 * where a colour beats a word.
 */

/** Sort weight: the worse a state is, the earlier the row appears. */
const SEVERITY: Record<string, number> = {
  FAILED: 0,
  UNREACHABLE: 1,
  STOPPED: 2,
  SCAN_QR_CODE: 3,
  STARTING: 4,
  OPENING: 4,
  WORKING: 5,
};

type SortKey = "severity" | "tenantName" | "name" | "status";

function liveState(session: FleetSession): string {
  return (session.liveStatus ?? session.status ?? "").toUpperCase();
}

function severityOf(session: FleetSession): number {
  return SEVERITY[liveState(session)] ?? 1;
}

/** Row tint by state. Not a badge tone: the whole row has to read as wrong. */
const ROW_TINT: Record<number, string> = {
  0: "bg-danger/5",
  1: "bg-danger/5",
  2: "bg-warning/5",
  3: "bg-warning/5",
};

const STATUS_STYLE: Record<string, string> = {
  FAILED: "bg-danger/15 text-danger",
  UNREACHABLE: "bg-danger/15 text-danger",
  STOPPED: "bg-surface-muted text-foreground",
  SCAN_QR_CODE: "bg-warning/15 text-warning",
  STARTING: "bg-warning/15 text-warning",
  OPENING: "bg-warning/15 text-warning",
  WORKING: "bg-primary/15 text-primary-strong",
};

export default function AdminFleetPage() {
  const token = useAuthToken();
  const { data, loading, error, refetch } = useApi(() => adminFleet.list({ token }), [token]);

  const broken = (data ?? []).filter((s) => liveState(s) !== "WORKING");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Fleet health</h1>
          <p className="text-sm text-muted-foreground">
            Live status for every WhatsApp session, across every tenant. Worst first.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refetch}>
          Refresh
        </Button>
      </div>

      {/* Lead with what is wrong, on the screen that knows it. */}
      {!loading && data && data.length > 0 ? (
        broken.length > 0 ? (
          <div className="rounded-2xl border border-danger/40 bg-danger/5 px-4 py-3 text-sm">
            <p className="font-semibold text-danger">
              {broken.length} of {data.length}{" "}
              {broken.length === 1 ? "number is not answering" : "numbers are not answering"}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {broken
                .map((s) => `${s.tenantName ?? s.name} (${s.liveStatus ?? s.status})`)
                .join(", ")}
            </p>
          </div>
        ) : (
          <div className="rounded-2xl border border-primary/30 bg-primary/5 px-4 py-3 text-sm font-semibold">
            All {data.length} {data.length === 1 ? "number is" : "numbers are"} answering.
          </div>
        )
      ) : null}

      <div className="overflow-hidden rounded-2xl border border-border bg-surface">
        {loading ? (
          <div className="space-y-3 p-5">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : error ? (
          <div className="p-5">
            <EmptyState
              icon={<Radio className="h-5 w-5" />}
              title="Couldn't load"
              description={error}
              action={
                <Button variant="outline" size="sm" onClick={refetch}>
                  Retry
                </Button>
              }
            />
          </div>
        ) : !data || data.length === 0 ? (
          <div className="p-5">
            <EmptyState
              icon={<Radio className="h-5 w-5" />}
              title="No sessions yet"
              description="Sessions appear here as tenants connect their WhatsApp numbers."
            />
          </div>
        ) : (
          <FleetTable sessions={data} onChanged={refetch} />
        )}
      </div>
    </div>
  );
}

function FleetTable({
  sessions,
  onChanged,
}: {
  sessions: FleetSession[];
  onChanged: () => void;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "broken" | SessionStatus>("all");
  // Severity, descending, is "failed first": the default the report asked for.
  const [sort, setSort] = useState<SortState<SortKey>>({ key: "severity", direction: "asc" });

  const rows = useMemo(() => {
    const filtered = sessions.filter((s) => {
      const state = liveState(s);
      if (filter === "broken" && state === "WORKING") return false;
      if (filter !== "all" && filter !== "broken" && state !== filter) return false;
      return matchesQuery(query, s.tenantName, s.name, s.label);
    });
    const direction = sort.direction === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      if (sort.key === "severity") {
        const bySeverity = direction * (severityOf(a) - severityOf(b));
        // Ties broken by tenant name so the list does not reshuffle between
        // refreshes, which on this screen looks like something changed.
        return bySeverity !== 0 ? bySeverity : compare(a.tenantName, b.tenantName);
      }
      if (sort.key === "status") return direction * compare(liveState(a), liveState(b));
      return direction * compare(a[sort.key], b[sort.key]);
    });
  }, [sessions, query, filter, sort]);

  const paging = usePaging(rows, 25);

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-border p-4">
        <SearchBox
          label="Search sessions"
          placeholder="Tenant or session name"
          value={query}
          onChange={setQuery}
        />
        <select
          aria-label="Filter by status"
          className={SELECT_CLASSES}
          value={filter}
          onChange={(e) => setFilter(e.target.value as typeof filter)}
        >
          <option value="all">Any status</option>
          <option value="broken">Not working</option>
          <option value="WORKING">Working</option>
          <option value="FAILED">Failed</option>
          <option value="STOPPED">Stopped</option>
          <option value="SCAN_QR_CODE">Waiting for a QR scan</option>
          <option value="STARTING">Starting</option>
        </select>
      </div>

      {rows.length === 0 ? (
        <div className="p-5">
          <EmptyState
            icon={<Radio className="h-5 w-5" />}
            title="No matches"
            description="No session matches that search and filter."
          />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <SortHeader
                  className="px-5 py-3"
                  column="tenantName"
                  label="Business"
                  sort={sort}
                  onSort={setSort}
                />
                <SortHeader
                  className="px-3 py-3"
                  column="name"
                  label="Session"
                  sort={sort}
                  onSort={setSort}
                />
                <SortHeader
                  className="px-3 py-3"
                  column="severity"
                  label="State"
                  sort={sort}
                  onSort={setSort}
                />
                <th className="px-5 py-3 text-right font-bold uppercase tracking-wider">Control</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {paging.slice.map((session) => {
                const state = liveState(session);
                return (
                  <tr key={session.name} className={ROW_TINT[severityOf(session)] ?? ""}>
                    <td className="px-5 py-3 font-semibold">
                      <Link
                        href={`/admin/tenants/${session.tenantId}`}
                        className="underline-offset-2 hover:underline"
                      >
                        {session.tenantName ?? session.tenantId.slice(0, 8)}
                      </Link>
                    </td>
                    <td className="px-3 py-3 font-mono text-xs text-muted-foreground">
                      {session.label || session.name}
                    </td>
                    <td className="px-3 py-3">
                      <span
                        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold ${
                          STATUS_STYLE[state] ?? "bg-surface-muted text-foreground"
                        }`}
                      >
                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-current" />
                        {state || "unknown"}
                      </span>
                      {session.liveStatus && session.liveStatus !== session.status ? (
                        <span className="ml-2 text-xs text-muted-foreground">
                          stored: {session.status}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-5 py-3">
                      <SessionControl session={session} onChanged={onChanged} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Pager
        page={paging.page}
        pages={paging.pages}
        from={paging.from}
        to={paging.to}
        total={paging.total}
        noun={paging.total === 1 ? "session" : "sessions"}
        onPage={paging.setPage}
      />
    </div>
  );
}
