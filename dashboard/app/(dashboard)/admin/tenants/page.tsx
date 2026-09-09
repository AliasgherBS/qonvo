"use client";

import { Building2, Check, ChevronDown, Copy, ScrollText } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type FormEvent } from "react";

import { ConsoleExceptions } from "@/components/admin/console-exceptions";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import {
  adminOverview,
  adminTenants,
  describeError,
  type AdminTenant,
  type CreateTenantResult,
  type TenantStatus,
} from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useApi, useAuthToken } from "@/lib/use-api";

const STATUS_TONE: Record<TenantStatus, "success" | "warning" | "default"> = {
  active: "success",
  onboarding: "warning",
  suspended: "default",
};

type SortKey = "name" | "ownerEmail" | "status" | "plan" | "createdAt";

/**
 * The console's front door.
 *
 * Reordered around findings A3, A5 and A7, and around the report's
 * "lead with what is wrong".
 *
 * The page used to open on six equal counters, with the exceptions -- a dead
 * session, a tenant over its quota -- available only by navigating to another
 * screen and reading a table. Now the exceptions lead and the counters are a
 * disclosure, because "how many businesses do we have" is a weekly question
 * rendered at the size of an urgent one.
 *
 * The counters also went stale on every mutation (A3): they came from a
 * separate fetch that `refetch()` on the table did not touch, so creating a
 * tenant left the table showing four rows under a tile reading "BUSINESSES 3".
 * An operator who trusts the tile clicks Create again. Both queries are owned
 * here now and refetched together, which is the only version of this that
 * cannot drift.
 */
export default function AdminTenantsPage() {
  const token = useAuthToken();
  const tenants = useApi(() => adminTenants.list({ token }), [token]);
  const overview = useApi(() => adminOverview.get({ token }), [token]);
  const [createOpen, setCreateOpen] = useState(false);
  const [created, setCreated] = useState<CreateTenantResult | null>(null);

  /** Any tenant mutation invalidates both the rows and the counters (A3). */
  function refreshAll() {
    tenants.refetch();
    overview.refetch();
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Tenants</h1>
          <p className="text-sm text-muted-foreground">
            Every business on Qonvo. Create tenants, manage lifecycle and plans.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/admin/audit"
            className="inline-flex items-center gap-1.5 text-sm font-semibold text-muted-foreground transition hover:text-foreground"
          >
            <ScrollText className="h-4 w-4" />
            Audit log
          </Link>
          <Button onClick={() => setCreateOpen(true)}>New tenant</Button>
        </div>
      </div>

      <ConsoleExceptions />

      <OverviewDisclosure data={overview.data} loading={overview.loading} />

      <div className="overflow-hidden rounded-2xl border border-border bg-surface">
        {tenants.loading ? (
          <div className="space-y-3 p-5">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : tenants.error ? (
          <div className="p-5">
            <EmptyState
              icon={<Building2 className="h-5 w-5" />}
              title="Couldn't load"
              description={tenants.error}
              action={
                <Button variant="outline" size="sm" onClick={refreshAll}>
                  Retry
                </Button>
              }
            />
          </div>
        ) : !tenants.data || tenants.data.length === 0 ? (
          <div className="p-5">
            <EmptyState
              icon={<Building2 className="h-5 w-5" />}
              title="No tenants yet"
              description="Create the first tenant to start onboarding a business."
            />
          </div>
        ) : (
          <TenantsTable tenants={tenants.data} />
        )}
      </div>

      <NewTenantDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(tenant) => {
          setCreateOpen(false);
          setCreated(tenant);
          refreshAll();
        }}
      />

      <TempPasswordDialog result={created} onClose={() => setCreated(null)} />
    </div>
  );
}

/**
 * The counters, collapsed.
 *
 * Kept, because they are the numbers somebody wants at the start of a month.
 * Collapsed, because they were above the only screen that reports an outage and
 * were the first thing the eye landed on.
 */
function OverviewDisclosure({
  data,
  loading,
}: {
  data: {
    totalTenants: number;
    connectedTenants: number;
    tenantsWithKnowledge: number;
    knowledgeSourcesReady: number;
    messages30d: number;
    cost30d: number;
  } | null;
  loading: boolean;
}) {
  const [open, setOpen] = useState(false);

  const tiles = [
    { label: "Businesses", value: data?.totalTenants, hint: "total tenants" },
    { label: "Connected", value: data?.connectedTenants, hint: "live WhatsApp session" },
    { label: "With knowledge", value: data?.tenantsWithKnowledge, hint: "ingested at least one" },
    {
      label: "Knowledge sources",
      value: data?.knowledgeSourcesReady,
      hint: "ready across platform",
    },
    { label: "Messages (30d)", value: data?.messages30d, hint: "in and out" },
    {
      label: "AI cost (30d)",
      value: data ? `$${data.cost30d.toFixed(2)}` : undefined,
      hint: "across all tenants",
    },
  ];

  return (
    <div className="rounded-2xl border border-border bg-surface">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-5 py-3 text-left"
      >
        <span className="text-sm font-semibold">
          Platform totals
          {loading ? null : (
            <span className="ml-2 font-normal text-muted-foreground">
              {data?.totalTenants ?? 0} businesses, {data?.connectedTenants ?? 0} connected,{" "}
              {(data?.messages30d ?? 0).toLocaleString()} messages in 30 days
            </span>
          )}
        </span>
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-muted-foreground transition ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open ? (
        <div className="grid grid-cols-2 gap-3 border-t border-border p-4 sm:grid-cols-3 lg:grid-cols-6">
          {tiles.map((t) => (
            <div key={t.label}>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t.label}
              </p>
              {loading ? (
                <Skeleton className="mt-2 h-7 w-14" />
              ) : (
                <p className="mt-1 text-2xl font-extrabold tracking-tight">{t.value ?? "0"}</p>
              )}
              <p className="mt-1 text-xs text-muted-foreground">{t.hint}</p>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function TenantsTable({ tenants }: { tenants: AdminTenant[] }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"all" | TenantStatus>("all");
  const [sort, setSort] = useState<SortState<SortKey>>({ key: "createdAt", direction: "desc" });

  const rows = useMemo(() => {
    const filtered = tenants.filter(
      (t) =>
        (status === "all" || t.status === status) &&
        // Both fields, because an operator arrives with whichever the customer
        // gave them: the business name from a WhatsApp message, or the email
        // from a support thread.
        matchesQuery(query, t.name, t.ownerEmail, t.ownerName, t.slug),
    );
    const direction = sort.direction === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      if (sort.key === "plan") return direction * compare(a.planKey ?? a.plan, b.planKey ?? b.plan);
      return direction * compare(a[sort.key], b[sort.key]);
    });
  }, [tenants, query, status, sort]);

  const paging = usePaging(rows, 25);

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-border p-4">
        <SearchBox
          label="Search tenants"
          placeholder="Business name or owner email"
          value={query}
          onChange={setQuery}
        />
        <select
          aria-label="Filter by status"
          className={SELECT_CLASSES}
          value={status}
          onChange={(e) => setStatus(e.target.value as "all" | TenantStatus)}
        >
          <option value="all">Any status</option>
          <option value="active">Active</option>
          <option value="onboarding">Onboarding</option>
          <option value="suspended">Suspended</option>
        </select>
      </div>

      {rows.length === 0 ? (
        <div className="p-5">
          <EmptyState
            icon={<Building2 className="h-5 w-5" />}
            title="No matches"
            description="No business matches that search and filter."
          />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <SortHeader
                  className="px-5 py-3"
                  column="name"
                  label="Business"
                  sort={sort}
                  onSort={setSort}
                />
                <SortHeader
                  className="px-3 py-3"
                  column="ownerEmail"
                  label="Owner"
                  sort={sort}
                  onSort={setSort}
                />
                <SortHeader
                  className="px-3 py-3"
                  column="status"
                  label="Status"
                  sort={sort}
                  onSort={setSort}
                />
                <SortHeader
                  className="px-3 py-3"
                  column="plan"
                  label="Plan"
                  sort={sort}
                  onSort={setSort}
                />
                <SortHeader
                  className="px-3 py-3"
                  column="createdAt"
                  label="Created"
                  sort={sort}
                  onSort={setSort}
                />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {paging.slice.map((tenant) => (
                <tr key={tenant.id}>
                  <td className="px-5 py-3 font-semibold">
                    <Link
                      href={`/admin/tenants/${tenant.id}`}
                      className="underline-offset-2 hover:underline"
                    >
                      {tenant.name}
                    </Link>
                  </td>
                  <td className="px-3 py-3 text-muted-foreground">{tenant.ownerEmail}</td>
                  <td className="px-3 py-3">
                    <Badge tone={STATUS_TONE[tenant.status]}>{tenant.status}</Badge>
                  </td>
                  <td className="px-3 py-3">
                    {/* The catalogue key, not the paid/trial label. "Paid" is
                        two values over a four-tier catalogue, and the pair
                        going out of step is finding F3. */}
                    <span className="font-semibold capitalize">
                      {tenant.planKey ?? tenant.plan}
                    </span>
                  </td>
                  {/* A7: the shared formatter. This column read "9/8/2026"
                      while the owner-facing product read "5 Sept 2026", and
                      `toLocaleDateString()` with no locale follows the
                      viewer's browser, so the same row read differently to us
                      and to them. */}
                  <td className="px-3 py-3 text-muted-foreground">
                    {formatDate(tenant.createdAt)}
                  </td>
                </tr>
              ))}
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
        noun={paging.total === 1 ? "business" : "businesses"}
        onPage={paging.setPage}
      />
    </div>
  );
}

function NewTenantDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (tenant: CreateTenantResult) => void;
}) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [ownerName, setOwnerName] = useState("");
  const [ownerEmail, setOwnerEmail] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || !slug.trim() || !ownerEmail.trim() || !ownerName.trim()) return;
    setSaving(true);
    try {
      const tenant = await adminTenants.create(
        {
          name: name.trim(),
          slug: slug.trim(),
          ownerEmail: ownerEmail.trim(),
          ownerName: ownerName.trim(),
        },
        { token },
      );
      setName("");
      setSlug("");
      setOwnerName("");
      setOwnerEmail("");
      onCreated(tenant);
    } catch (err) {
      toast({ title: "Couldn't create tenant", description: describeError(err), variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New tenant"
      description="Create a business and its owner account."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="tenant-name">Business name</Label>
          <Input id="tenant-name" value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="tenant-slug">Slug</Label>
          <Input
            id="tenant-slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="e.g. acme-cafe"
            required
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="owner-name">Owner name</Label>
          <Input
            id="owner-name"
            value={ownerName}
            onChange={(e) => setOwnerName(e.target.value)}
            required
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="owner-email">Owner email</Label>
          <Input
            id="owner-email"
            type="email"
            value={ownerEmail}
            onChange={(e) => setOwnerEmail(e.target.value)}
            required
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={saving}>
            {saving ? "Creating…" : "Create tenant"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function TempPasswordDialog({
  result,
  onClose,
}: {
  result: CreateTenantResult | null;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.tempPassword);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access denied. The password is still selectable and visible.
    }
  }

  return (
    <Dialog
      open={result != null}
      onClose={onClose}
      title="Tenant created"
      description={
        result
          ? `${result.name} is ready. Share this temporary password with ${result.ownerEmail} now.`
          : undefined
      }
    >
      {result ? (
        <div className="space-y-4">
          <div className="rounded-xl border border-border-strong bg-surface-muted px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Temporary password
            </p>
            <p className="mt-1 break-all font-mono text-sm font-bold">{result.tempPassword}</p>
          </div>
          <p className="text-xs text-danger">
            This is shown once and cannot be retrieved again. Copy it now.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={handleCopy}>
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
              {copied ? "Copied" : "Copy password"}
            </Button>
            <Button onClick={onClose}>Done</Button>
          </div>
        </div>
      ) : null}
    </Dialog>
  );
}
