"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { adminUsers, describeError, type AdminTenant } from "@/lib/api";
import { useAuthToken } from "@/lib/use-api";

/** Support tooling for a tenant: recover a locked-out owner. */
export function TenantSupportCard({ tenant }: { tenant: AdminTenant }) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ownerEmail: string; tempPassword: string } | null>(null);

  async function resetPassword() {
    setBusy(true);
    try {
      const res = await adminUsers.resetOwnerPassword(tenant.id, { token });
      setResult(res);
    } catch (err) {
      toast({ title: "Couldn't reset password", description: describeError(err), variant: "error" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Support</CardTitle>
          <CardDescription>Recover the owner when they&apos;re locked out.</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="text-sm">
            <span className="font-semibold">Owner password</span>
            <p className="text-xs text-muted-foreground">
              Generates a one-time password for {tenant.ownerEmail ?? "the owner"}. Relay it securely —
              it&apos;s shown only once.
            </p>
          </div>
          <Button variant="outline" size="sm" disabled={busy} onClick={resetPassword}>
            {busy ? "Resetting…" : "Reset owner password"}
          </Button>
        </div>
      </CardContent>

      <Dialog
        open={result !== null}
        onClose={() => setResult(null)}
        title="One-time password"
        description={`Give this to ${result?.ownerEmail ?? "the owner"}. It won't be shown again.`}
      >
        <div className="space-y-4">
          <code className="block break-all rounded-xl border border-border bg-muted px-3 py-2 font-mono text-sm">
            {result?.tempPassword}
          </code>
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => {
                if (result) navigator.clipboard?.writeText(result.tempPassword);
                toast({ title: "Copied", variant: "success" });
              }}
            >
              Copy
            </Button>
            <Button onClick={() => setResult(null)}>Done</Button>
          </div>
        </div>
      </Dialog>
    </Card>
  );
}
