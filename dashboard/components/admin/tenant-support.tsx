"use client";

import { Check, Copy, KeyRound, UserCheck } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { adminUsers, describeError, type AdminTenant } from "@/lib/api";
import { useAuthToken } from "@/lib/use-api";

/**
 * The two support recoveries, kept apart from the tenant's settings.
 *
 * Both used to sit in the same visual register as a name field, which is the
 * general shape of finding A1 and the report's "separate reading from doing":
 * a control that mails a customer a new password should not look like a text
 * input.
 *
 * The impersonation button is finding A4. `POST .../impersonate` works, is
 * properly scoped (the token carries the *owner's* identity, so it is subject
 * to normal RLS) and carries `acting_as` so every action taken inside the
 * session is attributed to the admin behind it rather than to the customer.
 * Nothing on any page called it.
 */
export function TenantSupport({ tenant }: { tenant: AdminTenant }) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Support</CardTitle>
          <CardDescription>
            Getting an owner back in, and seeing what they see. Both are recorded in the audit log
            against your account.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="divide-y divide-border">
        <ResetPassword tenant={tenant} />
        <Impersonate tenant={tenant} />
      </CardContent>
    </Card>
  );
}

function Row({
  icon,
  title,
  children,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
  action: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 py-4 first:pt-0 last:pb-0">
      <div className="flex min-w-[16rem] flex-1 gap-3">
        <span className="mt-0.5 text-muted-foreground">{icon}</span>
        <div className="text-sm">
          <p className="font-semibold">{title}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{children}</p>
        </div>
      </div>
      {action}
    </div>
  );
}

function ResetPassword({ tenant }: { tenant: AdminTenant }) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ownerEmail: string; tempPassword: string } | null>(null);

  async function reset() {
    setBusy(true);
    try {
      setResult(await adminUsers.resetOwnerPassword(tenant.id, { token }));
    } catch (err) {
      toast({ title: "Couldn't reset password", description: describeError(err), variant: "error" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Row
        icon={<KeyRound className="h-4 w-4" />}
        title="Reset the owner's password"
        action={
          <Button
            variant="outline"
            size="sm"
            className="border-danger/50 text-danger"
            disabled={busy}
            onClick={reset}
          >
            {busy ? "Resetting…" : "Reset password"}
          </Button>
        }
      >
        Replaces {tenant.ownerEmail ?? "the owner"}&apos;s password with a one-time one, immediately.
        Their current password stops working, so only do this when they have asked.
      </Row>

      <SecretDialog
        open={result !== null}
        title="One-time password"
        description={`Give this to ${result?.ownerEmail ?? "the owner"} over a channel you trust. It is not shown again.`}
        secret={result?.tempPassword ?? ""}
        onClose={() => setResult(null)}
      />
    </>
  );
}

function Impersonate({ tenant }: { tenant: AdminTenant }) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [session, setSession] = useState<{ accessToken: string; ownerEmail: string } | null>(null);

  async function start() {
    setBusy(true);
    try {
      setSession(await adminUsers.impersonate(tenant.id, { token }));
      setConfirm(false);
    } catch (err) {
      toast({ title: "Couldn't start session", description: describeError(err), variant: "error" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Row
        icon={<UserCheck className="h-4 w-4" />}
        title="Sign in as this owner"
        action={
          <Button variant="outline" size="sm" disabled={busy} onClick={() => setConfirm(true)}>
            Start support session
          </Button>
        }
      >
        Mints an owner-scoped token for {tenant.ownerEmail ?? "this business"}. It can read and
        change everything the owner can, including their customers&apos; conversations. Every action
        it takes is recorded against your account, not theirs.
      </Row>

      <Dialog
        open={confirm}
        onClose={() => setConfirm(false)}
        title="Start a support session?"
        description={`This gives you the same access as ${tenant.ownerEmail ?? "the owner"}: their inbox, their customers' messages, their configuration and their integrations. It is audited as "impersonated by you" and lasts as long as a normal sign-in.`}
      >
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => setConfirm(false)}>
            Cancel
          </Button>
          <Button disabled={busy} onClick={start}>
            {busy ? "Starting…" : "Start session"}
          </Button>
        </div>
      </Dialog>

      <SecretDialog
        open={session !== null}
        title="Support session token"
        description={`An owner-scoped token for ${session?.ownerEmail ?? "the owner"}. Send it as "Authorization: Bearer <token>" against the API. Every request it makes is attributed to you in the audit log.`}
        secret={session?.accessToken ?? ""}
        onClose={() => setSession(null)}
      />
    </>
  );
}

/**
 * A value shown once, that the operator has to move somewhere else.
 *
 * Both secrets here are single-issue: the password is already live on the
 * account by the time this renders, and the token cannot be re-fetched. So the
 * dialog says so rather than implying it can be looked up again later.
 */
function SecretDialog({
  open,
  title,
  description,
  secret,
  onClose,
}: {
  open: boolean;
  title: string;
  description: string;
  secret: string;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard blocked. The value is on screen and selectable.
    }
  }

  return (
    <Dialog
      open={open}
      onClose={() => {
        setCopied(false);
        onClose();
      }}
      title={title}
      description={description}
    >
      <div className="space-y-4">
        <code className="block max-h-40 overflow-auto break-all rounded-xl border border-border bg-surface-muted px-3 py-2 font-mono text-xs">
          {secret}
        </code>
        <p className="text-xs text-danger">Shown once. It cannot be retrieved again.</p>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={copy}>
            {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            {copied ? "Copied" : "Copy"}
          </Button>
          <Button
            onClick={() => {
              setCopied(false);
              onClose();
            }}
          >
            Done
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
