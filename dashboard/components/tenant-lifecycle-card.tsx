"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { adminTenants, describeError, type AdminTenant } from "@/lib/api";
import { useAuthToken } from "@/lib/use-api";

export function TenantLifecycleCard({ tenant, onChanged }: { tenant: AdminTenant; onChanged: () => void }) {
  const token = useAuthToken();
  const { toast } = useToast();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const suspended = tenant.status === "suspended";

  async function patch(payload: Parameters<typeof adminTenants.update>[1], ok: string) {
    setBusy(true);
    try {
      await adminTenants.update(tenant.id, payload, { token });
      toast({ title: ok, variant: "success" });
      onChanged();
    } catch (err) {
      toast({ title: "Couldn't update", description: describeError(err), variant: "error" });
    } finally {
      setBusy(false);
    }
  }

  const trialEnds = tenant.trialEndsAt ? new Date(tenant.trialEndsAt) : null;
  const daysLeft = trialEnds ? Math.ceil((trialEnds.getTime() - Date.now()) / 86_400_000) : null;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Manage tenant</CardTitle>
          <CardDescription>Status, plan, and offboarding.</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Status */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm">
            <span className="font-semibold">Status</span>
            <Badge tone={suspended ? "danger" : "success"}>{tenant.status}</Badge>
          </div>
          <Button
            variant={suspended ? undefined : "outline"}
            size="sm"
            disabled={busy}
            onClick={() =>
              patch({ status: suspended ? "active" : "suspended" }, suspended ? "Reactivated" : "Suspended")
            }
          >
            {suspended ? "Reactivate" : "Suspend"}
          </Button>
        </div>
        {suspended ? (
          <p className="rounded-xl bg-warning/10 px-3 py-2 text-xs text-muted-foreground">
            Suspended. The bot is silent for this tenant until reactivated.
          </p>
        ) : null}

        {/* Plan / trial */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
          <div className="text-sm">
            <span className="font-semibold">Plan</span>{" "}
            <Badge tone={tenant.plan === "paid" ? "success" : "default"}>{tenant.plan}</Badge>
            {tenant.plan === "trial" && daysLeft !== null ? (
              <span className="ml-2 text-xs text-muted-foreground">
                trial {daysLeft > 0 ? `ends in ${daysLeft}d` : "expired"}
              </span>
            ) : null}
          </div>
          <div className="flex gap-2">
            {tenant.plan !== "paid" ? (
              <Button variant="outline" size="sm" disabled={busy} onClick={() => patch({ plan: "paid" }, "Marked paid")}>
                Mark as paid
              </Button>
            ) : (
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() =>
                  patch(
                    { plan: "trial", trialEndsAt: new Date(Date.now() + 14 * 86_400_000).toISOString() },
                    "Trial reset",
                  )
                }
              >
                Start 14-day trial
              </Button>
            )}
          </div>
        </div>

        {/* Danger zone */}
        <div className="rounded-xl border border-danger/40 bg-danger/5 p-4">
          <p className="text-sm font-semibold text-danger">Danger zone</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Permanently delete this business and all its data (sessions, conversations, knowledge). This
            can&apos;t be undone.
          </p>
          <Button variant="outline" size="sm" className="mt-3 border-danger/50 text-danger" onClick={() => setConfirmDelete(true)}>
            Delete tenant
          </Button>
        </div>
      </CardContent>

      <DeleteTenantDialog
        open={confirmDelete}
        tenant={tenant}
        onClose={() => setConfirmDelete(false)}
        onDeleted={() => {
          toast({ title: "Tenant deleted", variant: "success" });
          router.push("/admin/tenants");
        }}
      />
    </Card>
  );
}

function DeleteTenantDialog({
  open,
  tenant,
  onClose,
  onDeleted,
}: {
  open: boolean;
  tenant: AdminTenant;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    setDeleting(true);
    try {
      await adminTenants.remove(tenant.id, { token });
      onDeleted();
    } catch (err) {
      toast({ title: "Couldn't delete tenant", description: describeError(err), variant: "error" });
      setDeleting(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Delete tenant"
      description={`This permanently deletes "${tenant.name}" and all its data. Type the business name to confirm.`}
    >
      <div className="space-y-4">
        <Input
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          placeholder={tenant.name}
          aria-label="Type the business name to confirm"
        />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            className="border-danger/50 bg-danger text-danger-foreground hover:bg-danger/90"
            disabled={deleting || confirmText !== tenant.name}
            onClick={handleDelete}
          >
            {deleting ? "Deleting…" : "Delete permanently"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
