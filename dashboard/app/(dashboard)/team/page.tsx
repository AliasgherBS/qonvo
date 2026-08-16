"use client";

import { Download, UserPlus, Users } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { account, describeError, team } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";

export default function TeamPage() {
  const token = useAuthToken();
  const { data, loading, error, refetch } = useApi(() => team.get({ token }), [token]);

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Team</h1>
          <p className="text-sm text-muted-foreground">
            Invite staff or co-owners to share the inbox. Owners manage the team and billing.
          </p>
        </div>
        <ExportButton />
      </div>

      <InviteForm onInvited={refetch} />

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Members</CardTitle>
            <CardDescription>Everyone with access to this workspace.</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {[0, 1].map((i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : error ? (
            <EmptyState
              icon={<Users className="h-5 w-5" />}
              title="Couldn't load team"
              description={error}
              action={
                <Button variant="outline" size="sm" onClick={refetch}>
                  Retry
                </Button>
              }
            />
          ) : (
            <ul className="divide-y divide-border">
              {data?.members.map((m) => (
                <li key={m.userId} className="flex items-center justify-between gap-3 py-2.5">
                  <div>
                    <p className="text-sm font-semibold">{m.fullName || m.email}</p>
                    <p className="text-xs text-muted-foreground">{m.email}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge tone={m.role === "owner" ? "success" : "default"}>{m.role}</Badge>
                    {m.role !== "owner" ? (
                      <RemoveMemberButton userId={m.userId} onRemoved={refetch} />
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {data && data.invitations.length > 0 ? (
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Pending invitations</CardTitle>
              <CardDescription>Invites that haven&apos;t been accepted yet.</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <ul className="divide-y divide-border">
              {data.invitations.map((inv) => (
                <li key={inv.id} className="flex items-center justify-between gap-3 py-2.5">
                  <div>
                    <p className="text-sm font-semibold">{inv.email}</p>
                    <p className="text-xs text-muted-foreground">
                      {inv.role} · expires {new Date(inv.expiresAt).toLocaleDateString()}
                    </p>
                  </div>
                  <RevokeInviteButton id={inv.id} onRevoked={refetch} />
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function InviteForm({ onInvited }: { onInvited: () => void }) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("staff");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    try {
      await team.invite({ email: email.trim(), role }, { token });
      toast({ title: "Invitation sent", description: `We emailed ${email.trim()}.`, variant: "success" });
      setEmail("");
      onInvited();
    } catch (err) {
      toast({ title: "Couldn't invite", description: describeError(err), variant: "error" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <UserPlus className="h-5 w-5 text-primary" />
          <div>
            <CardTitle>Invite a teammate</CardTitle>
            <CardDescription>They get an email link to set up their account.</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <div className="min-w-[16rem] flex-1 space-y-1.5">
            <Label htmlFor="invite-email">Email</Label>
            <Input
              id="invite-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="teammate@company.com"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="invite-role">Role</Label>
            <select
              id="invite-role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="h-10 rounded-xl border border-border bg-surface px-3 text-sm"
            >
              <option value="staff">Staff</option>
              <option value="owner">Owner</option>
            </select>
          </div>
          <Button type="submit" disabled={busy || !email.trim()}>
            {busy ? "Sending…" : "Send invite"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function RevokeInviteButton({ id, onRevoked }: { id: string; onRevoked: () => void }) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant="outline"
      size="sm"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await team.revokeInvitation(id, { token });
          onRevoked();
        } catch (err) {
          toast({ title: "Couldn't revoke", description: describeError(err), variant: "error" });
          setBusy(false);
        }
      }}
    >
      Revoke
    </Button>
  );
}

function RemoveMemberButton({ userId, onRemoved }: { userId: string; onRemoved: () => void }) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant="outline"
      size="sm"
      className="border-danger/50 text-danger"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await team.removeMember(userId, { token });
          toast({ title: "Member removed", variant: "success" });
          onRemoved();
        } catch (err) {
          toast({ title: "Couldn't remove", description: describeError(err), variant: "error" });
          setBusy(false);
        }
      }}
    >
      Remove
    </Button>
  );
}

function ExportButton() {
  const token = useAuthToken();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant="outline"
      size="sm"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          const data = await account.export({ token });
          const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `qonvo-export-${new Date().toISOString().slice(0, 10)}.json`;
          a.click();
          URL.revokeObjectURL(url);
        } catch (err) {
          toast({ title: "Export failed", description: describeError(err), variant: "error" });
        } finally {
          setBusy(false);
        }
      }}
    >
      <Download className="mr-1.5 h-4 w-4" />
      {busy ? "Exporting…" : "Export data"}
    </Button>
  );
}
