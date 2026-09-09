"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AuditList } from "@/components/admin/audit-list";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * The audit log (finding A2).
 *
 * The rows have existed for some time: the console writes one on every
 * mutation, activation writes one with a readiness snapshot, and every
 * owner-side action has written one since X8. Nothing read them. Every
 * plausible endpoint answered 404 and there was no page, so "who suspended this
 * tenant", "who reset that password" and "when was this rep switched off" all
 * meant opening psql.
 *
 * `?tenant=<id>` filters to one business, which is how the tenant detail page's
 * History tab links out to the full log.
 */
export default function AdminAuditPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full rounded-2xl" />}>
      <AuditPageBody />
    </Suspense>
  );
}

function AuditPageBody() {
  const params = useSearchParams();
  const tenantId = params.get("tenant") ?? undefined;

  return (
    <div className="space-y-6">
      <div>
        {tenantId ? (
          <Link
            href={`/admin/tenants/${tenantId}`}
            className="mb-2 inline-flex items-center gap-1.5 text-sm font-semibold text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to the tenant
          </Link>
        ) : null}
        <h1 className="text-2xl font-extrabold tracking-tight">Audit log</h1>
        <p className="text-sm text-muted-foreground">
          Who did what, newest first. Covers both this console and the owners&apos; own actions.
          {tenantId ? " Filtered to one business." : ""}
        </p>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border bg-surface">
        <AuditList tenantId={tenantId} />
      </div>

      <p className="text-xs text-muted-foreground">
        A support session shows the owner it acted as, with the admin behind it named separately.
        Configuration entries record which fields changed and never their values: the payment
        details the rep reads out verbatim would otherwise be duplicated here with a different
        retention story.
      </p>
    </div>
  );
}
