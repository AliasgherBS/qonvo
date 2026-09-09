"use client";

import { ArrowLeft, Building2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { AuditList } from "@/components/admin/audit-list";
import { TenantLifecycle } from "@/components/admin/tenant-lifecycle";
import { TenantSupport } from "@/components/admin/tenant-support";
import { AllConfigSections } from "@/components/settings/tenant-config";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { adminTenants, type TenantStatus } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useApi, useAuthToken } from "@/lib/use-api";

const STATUS_TONE: Record<TenantStatus, "success" | "warning" | "default"> = {
  active: "success",
  onboarding: "warning",
  suspended: "default",
};

const TABS = [
  { key: "lifecycle", label: "Lifecycle and plan" },
  { key: "support", label: "Support" },
  { key: "config", label: "Configuration" },
  { key: "history", label: "History" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

/**
 * One tenant, given a spine.
 *
 * It used to be a single scroll: lifecycle, then support, then the entire owner
 * configuration form inline, so a four-hundred-entry timezone select sat
 * between "Delete tenant" and the persona picker. Everything on the page was
 * reachable and nothing on it was findable, and the two irreversible controls
 * shared a visual register with a text input.
 *
 * Four tabs, in the order an operator arrives with a question: what is this
 * business on, how do I get its owner back in, what is it configured to say,
 * and what has happened to it. History is the audit log filtered to this tenant
 * (finding A2) -- the answer to "who suspended us" on the same page as the
 * button that did it.
 */
export default function AdminTenantDetailPage() {
  const params = useParams<{ id: string }>();
  const tenantId = params.id;
  const token = useAuthToken();
  const [tab, setTab] = useState<TabKey>("lifecycle");

  const {
    data: tenant,
    loading: tenantLoading,
    error: tenantError,
    refetch: refetchTenant,
  } = useApi(() => adminTenants.get(tenantId, { token }), [tenantId, token]);
  const {
    data: config,
    loading: configLoading,
    error: configError,
    refetch: refetchConfig,
  } = useApi(() => adminTenants.getConfig(tenantId, { token }), [tenantId, token]);

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <Link
          href="/admin/tenants"
          className="inline-flex items-center gap-1.5 text-sm font-semibold text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          All tenants
        </Link>
      </div>

      {tenantLoading ? (
        <Skeleton className="h-20 w-full rounded-2xl" />
      ) : tenantError || !tenant ? (
        <Card>
          <CardContent>
            <EmptyState
              icon={<Building2 className="h-5 w-5" />}
              title="Couldn't load tenant"
              description={tenantError ?? "This tenant couldn't be found."}
              action={
                <Button variant="outline" size="sm" onClick={refetchTenant}>
                  Retry
                </Button>
              }
            />
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-border bg-surface p-5">
            <div>
              <h1 className="text-2xl font-extrabold tracking-tight">{tenant.name}</h1>
              <p className="text-sm text-muted-foreground">
                {tenant.ownerName} · {tenant.ownerEmail}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                <span className="font-mono">{tenant.slug}</span> · created{" "}
                {formatDate(tenant.createdAt)}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={tenant.plan === "paid" ? "success" : "default"}>
                {tenant.subscription?.planName ?? tenant.planKey ?? tenant.plan}
              </Badge>
              <Badge tone={STATUS_TONE[tenant.status]}>{tenant.status}</Badge>
            </div>
          </div>

          <div
            role="tablist"
            aria-label="Tenant sections"
            className="flex flex-wrap gap-1 rounded-full border border-border bg-surface p-1"
          >
            {TABS.map((entry) => (
              <button
                key={entry.key}
                role="tab"
                aria-selected={tab === entry.key}
                onClick={() => setTab(entry.key)}
                className={`rounded-full px-4 py-1.5 text-sm font-semibold transition ${
                  tab === entry.key
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {entry.label}
              </button>
            ))}
          </div>

          {tab === "lifecycle" ? (
            <TenantLifecycle tenant={tenant} onChanged={refetchTenant} />
          ) : null}

          {tab === "support" ? <TenantSupport tenant={tenant} /> : null}

          {tab === "config" ? (
            <div className="space-y-3">
              {/* A8: the config form's device hints are written for the owner
                  reading their own Business page. On an operator's screen,
                  configuring somebody else's salon, "this device is in
                  Asia/Karachi, use that instead" is advice to apply the wrong
                  timezone. Suppressed via `deviceHints`, and said out loud
                  here, because an operator editing a customer's settings
                  should be reminded whose settings they are. */}
              <p className="rounded-xl border border-warning/40 bg-warning/5 px-4 py-2.5 text-xs text-muted-foreground">
                You are editing <span className="font-semibold">{tenant.name}</span>&apos;s own
                settings. This is the same form its owner sees, and saving here changes what their
                rep says to their customers.
              </p>
              {configLoading ? (
                <div className="space-y-3">
                  {[0, 1, 2].map((i) => (
                    <Skeleton key={i} className="h-24 w-full rounded-2xl" />
                  ))}
                </div>
              ) : configError || !config ? (
                <Card>
                  <CardContent>
                    <EmptyState
                      icon={<Building2 className="h-5 w-5" />}
                      title="Couldn't load config"
                      description={configError ?? "This tenant's config couldn't be loaded."}
                      action={
                        <Button variant="outline" size="sm" onClick={refetchConfig}>
                          Retry
                        </Button>
                      }
                    />
                  </CardContent>
                </Card>
              ) : (
                <AllConfigSections
                  config={config}
                  deviceHints={false}
                  onSave={(next) =>
                    adminTenants.updateConfig(tenantId, next, { token }).then(() => undefined)
                  }
                />
              )}
            </div>
          ) : null}

          {tab === "history" ? (
            <div className="overflow-hidden rounded-2xl border border-border bg-surface">
              <AuditList tenantId={tenantId} />
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
