"use client";

import { ScrollText, UserCog } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { SearchBox, SELECT_CLASSES } from "@/components/admin/table-controls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { adminAudit, type AuditEntry } from "@/lib/api/admin-extras";
import { formatDateTime, formatRelative } from "@/lib/format";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * The audit trail, read back (finding A2).
 *
 * `audit_log` had three writers and no reader: no route, no page, so "who
 * suspended this tenant", "who reset that password" and "when was this rep
 * switched off" -- the first three questions of any support conversation -- all
 * needed psql. Impersonation is audited precisely so somebody can review it,
 * and nobody could.
 *
 * Paged on the server rather than in the browser, unlike the tenant and fleet
 * tables. Those are one row per tenant; this one grows for as long as the
 * product runs.
 *
 * Filters are substring matches, because an operator arrives knowing a fragment
 * of a name and the word "suspend", not a whole address and `tenant.update`.
 */

const PAGE_SIZE = 50;

/** Actions worth their own filter entry, phrased as the question they answer. */
const ACTION_FILTERS: { value: string; label: string }[] = [
  { value: "", label: "Everything" },
  { value: "tenant.", label: "Tenant lifecycle" },
  { value: "impersonate", label: "Support sessions" },
  { value: "password", label: "Password resets" },
  { value: "activation", label: "Rep switched on or off" },
  { value: "subscription", label: "Plan changes" },
  { value: "session.", label: "WhatsApp session control" },
  { value: "config", label: "Configuration changes" },
];

/** Danger reads as danger. A logout and a rename are not the same event. */
function toneFor(action: string): "danger" | "warning" | "info" | "default" {
  if (action.includes("delete") || action.includes("logout") || action.includes("password")) {
    return "danger";
  }
  if (action.includes("impersonate")) return "warning";
  if (action.includes("subscription") || action.includes("activation")) return "info";
  return "default";
}

export function AuditList({ tenantId, compact = false }: { tenantId?: string; compact?: boolean }) {
  const token = useAuthToken();
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [offset, setOffset] = useState(0);

  const limit = compact ? 10 : PAGE_SIZE;
  const { data, loading, error, refetch } = useApi(
    () => adminAudit.list({ tenantId, actor, action, limit, offset }, { token }),
    [token, tenantId, actor, action, limit, offset],
  );

  if (loading && !data) {
    return (
      <div className="space-y-3 p-5">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-9 w-full" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-5">
        <EmptyState
          icon={<ScrollText className="h-5 w-5" />}
          title="Couldn't load the audit log"
          description={error}
          action={
            <Button variant="outline" size="sm" onClick={refetch}>
              Retry
            </Button>
          }
        />
      </div>
    );
  }

  const page = data ?? { items: [], total: 0, limit, offset };
  const pageCount = Math.max(1, Math.ceil(page.total / limit));
  const pageIndex = Math.floor(page.offset / limit);

  return (
    <div>
      {!compact ? (
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-4">
          <SearchBox
            label="Filter by actor email"
            placeholder="Who did it: part of an email"
            value={actor}
            onChange={(next) => {
              setActor(next);
              setOffset(0);
            }}
          />
          <select
            aria-label="Filter by action"
            className={SELECT_CLASSES}
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setOffset(0);
            }}
          >
            {ACTION_FILTERS.map((entry) => (
              <option key={entry.value} value={entry.value}>
                {entry.label}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {page.items.length === 0 ? (
        <div className="p-5">
          <EmptyState
            icon={<ScrollText className="h-5 w-5" />}
            title="Nothing recorded"
            description={
              actor || action
                ? "No entries match that filter."
                : "Actions taken here and by owners are recorded as they happen."
            }
          />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-5 py-3">When</th>
                <th className="px-3 py-3">Action</th>
                <th className="px-3 py-3">Who</th>
                {!tenantId ? <th className="px-3 py-3">Business</th> : null}
                <th className="px-3 py-3">Detail</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {page.items.map((entry) => (
                <AuditRow key={entry.id} entry={entry} showTenant={!tenantId} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3 text-xs text-muted-foreground">
        <span>
          {page.total === 0
            ? "No entries"
            : `${page.offset + 1} to ${Math.min(page.total, page.offset + page.items.length)} of ${page.total} entries`}
        </span>
        {compact ? (
          tenantId ? (
            <Link
              href={`/admin/audit?tenant=${tenantId}`}
              className="font-semibold text-primary-strong underline-offset-2 hover:underline"
            >
              Open the full log
            </Link>
          ) : null
        ) : pageCount > 1 ? (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page.offset === 0}
              onClick={() => setOffset(Math.max(0, page.offset - limit))}
            >
              Newer
            </Button>
            <span className="tabular-nums">
              {pageIndex + 1} / {pageCount}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page.offset + limit >= page.total}
              onClick={() => setOffset(page.offset + limit)}
            >
              Older
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function AuditRow({ entry, showTenant }: { entry: AuditEntry; showTenant: boolean }) {
  const detail = Object.entries(entry.meta);

  return (
    <tr>
      <td className="whitespace-nowrap px-5 py-3 text-muted-foreground" title={entry.createdAt}>
        <span className="font-semibold text-foreground">{formatRelative(entry.createdAt)}</span>
        <span className="block text-xs">{formatDateTime(entry.createdAt)}</span>
      </td>
      <td className="px-3 py-3">
        <Badge tone={toneFor(entry.action)}>{entry.action}</Badge>
      </td>
      <td className="px-3 py-3">
        <span className="font-semibold">{entry.actorEmail ?? "system"}</span>
        {entry.actorRole ? (
          <span className="block text-xs text-muted-foreground">{entry.actorRole}</span>
        ) : null}
        {/* An impersonated token carries the owner's identity, so without this
            the row reads as the customer having done it. */}
        {entry.impersonatedBy ? (
          <span className="mt-0.5 inline-flex items-center gap-1 text-xs font-semibold text-warning">
            <UserCog className="h-3 w-3" />
            impersonated by {entry.impersonatedBy}
          </span>
        ) : null}
      </td>
      {showTenant ? (
        <td className="px-3 py-3">
          <Link
            href={`/admin/tenants/${entry.tenantId}`}
            className="text-muted-foreground underline-offset-2 hover:underline"
          >
            {entry.tenantName ?? entry.tenantId.slice(0, 8)}
          </Link>
        </td>
      ) : null}
      <td className="px-3 py-3 text-xs text-muted-foreground">
        {entry.target ? <span className="block break-all font-mono">{entry.target}</span> : null}
        {detail.length > 0 ? (
          <span className="block">
            {detail.map(([key, value]) => `${key}: ${describeValue(value)}`).join(" · ")}
          </span>
        ) : null}
      </td>
    </tr>
  );
}

/** Meta values are whatever the writer put there: names, keys, small lists. */
function describeValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
