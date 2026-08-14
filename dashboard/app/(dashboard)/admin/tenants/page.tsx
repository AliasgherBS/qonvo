"use client";

import { Building2, Check, Copy } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";

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
import { useApi, useAuthToken } from "@/lib/use-api";

const STATUS_TONE: Record<TenantStatus, "success" | "warning" | "default"> = {
  active: "success",
  onboarding: "warning",
  suspended: "default",
};

export default function AdminTenantsPage() {
  const token = useAuthToken();
  const { data, loading, error, refetch } = useApi(() => adminTenants.list({ token }), [token]);
  const [createOpen, setCreateOpen] = useState(false);
  const [created, setCreated] = useState<CreateTenantResult | null>(null);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Tenants</h1>
          <p className="text-sm text-muted-foreground">
            Every business on Qonvo — create tenants, invite owners, manage lifecycle.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>New tenant</Button>
      </div>

      <OverviewTiles />

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
              icon={<Building2 className="h-5 w-5" />}
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
              icon={<Building2 className="h-5 w-5" />}
              title="No tenants yet"
              description="Create the first tenant to start onboarding a business."
            />
          </div>
        ) : (
          <TenantsTable tenants={data} />
        )}
      </div>

      <NewTenantDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(tenant) => {
          setCreateOpen(false);
          setCreated(tenant);
          refetch();
        }}
      />

      <TempPasswordDialog result={created} onClose={() => setCreated(null)} />
    </div>
  );
}

function OverviewTiles() {
  const token = useAuthToken();
  const { data, loading } = useApi(() => adminOverview.get({ token }), [token]);

  const tiles = [
    { label: "Businesses", value: data?.totalTenants, hint: "total tenants" },
    { label: "Connected", value: data?.connectedTenants, hint: "live WhatsApp session" },
    { label: "With knowledge", value: data?.tenantsWithKnowledge, hint: "ingested ≥1 source" },
    { label: "Knowledge sources", value: data?.knowledgeSourcesReady, hint: "ready across platform" },
    { label: "Messages (30d)", value: data?.messages30d, hint: "in + out" },
    {
      label: "AI cost (30d)",
      value: data ? `$${data.cost30d.toFixed(2)}` : undefined,
      hint: "across all tenants",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-2xl border border-border bg-surface p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t.label}</p>
          {loading ? (
            <Skeleton className="mt-2 h-7 w-14" />
          ) : (
            <p className="mt-1 text-2xl font-extrabold tracking-tight">{t.value ?? "—"}</p>
          )}
          <p className="mt-1 text-xs text-muted-foreground">{t.hint}</p>
        </div>
      ))}
    </div>
  );
}

function TenantsTable({ tenants }: { tenants: AdminTenant[] }) {
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
        <tr>
          <th className="px-5 py-3">Business</th>
          <th className="px-5 py-3">Owner</th>
          <th className="px-5 py-3">Status</th>
          <th className="px-5 py-3">Created</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {tenants.map((tenant) => (
          <tr key={tenant.id}>
            <td className="px-5 py-3 font-semibold">
              <Link href={`/admin/tenants/${tenant.id}`} className="hover:underline">
                {tenant.name}
              </Link>
            </td>
            <td className="px-5 py-3 text-muted-foreground">{tenant.ownerEmail}</td>
            <td className="px-5 py-3">
              <Badge tone={STATUS_TONE[tenant.status]}>{tenant.status}</Badge>
            </td>
            <td className="px-5 py-3 text-muted-foreground">
              {new Date(tenant.createdAt).toLocaleDateString()}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
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
        { name: name.trim(), slug: slug.trim(), ownerEmail: ownerEmail.trim(), ownerName: ownerName.trim() },
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
    <Dialog open={open} onClose={onClose} title="New tenant" description="Create a business and invite its owner.">
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
          <Input id="owner-name" value={ownerName} onChange={(e) => setOwnerName(e.target.value)} required />
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

function TempPasswordDialog({ result, onClose }: { result: CreateTenantResult | null; onClose: () => void }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.tempPassword);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access denied — the password is still selectable/visible.
    }
  }

  return (
    <Dialog
      open={result != null}
      onClose={onClose}
      title="Tenant created"
      description={result ? `${result.name} is ready — share this temporary password with ${result.ownerEmail} now.` : undefined}
    >
      {result ? (
        <div className="space-y-4">
          <div className="rounded-xl border border-border-strong bg-surface-muted px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Temporary password</p>
            <p className="mt-1 break-all font-mono text-sm font-bold">{result.tempPassword}</p>
          </div>
          <p className="text-xs text-danger">
            This is shown once and can&apos;t be retrieved again — copy it now.
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
