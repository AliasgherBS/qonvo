"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { SELECT_CLASSES } from "@/components/admin/table-controls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { adminTenants, describeError, type AdminTenant } from "@/lib/api";
import { adminPlans, adminSubscription } from "@/lib/api/admin-extras";
import { formatDate } from "@/lib/format";
import { TRIAL_DAYS } from "@/lib/plan";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * A tenant's lifecycle: status, plan, trial clock, offboarding.
 *
 * The plan control is the whole of finding F3. It used to be a two-state
 * toggle, "Mark as paid" against a button that restarted the trial clock, and
 * both halves wrote `tenants.plan` through `PATCH /api/admin/tenants/{id}`.
 *
 * That column is a *label*. The numbers the pipeline enforces live in
 * `tenant_config.entitlements`, and only `apply_plan` writes them, deriving
 * every one from the catalogue in `backend/app/billing/plans.py`. So marking a
 * customer paid moved the label and left the quota:
 *
 *     test01              | plan: paid | messages allowed: 1000
 *     QA Throwaway Salon  | plan: paid | messages allowed: the trial's
 *
 * Take a bank transfer, mark the customer paid, and they hit a wall at the
 * trial allowance while this page reports a paid plan. The endpoint that does it
 * properly already existed and had no interface (finding A4), so the control is
 * now a picker over the real catalogue keys, pointed at that endpoint.
 *
 * The entitlements it produced are rendered next to it, because the pair going
 * out of step is precisely what happened and an operator has to be able to see
 * that from the tenant's own page rather than from psql.
 */

const ENTITLEMENT_LABELS: { key: string; label: string; format?: (n: number) => string }[] = [
  { key: "monthly_message_quota", label: "Messages / month" },
  { key: "monthly_voice_minutes", label: "Voice minutes" },
  { key: "seats", label: "Seats" },
  { key: "knowledge_sources", label: "Knowledge sources" },
  {
    key: "knowledge_chars",
    label: "Knowledge characters",
    format: (n) => `${(n / 1_000_000).toFixed(1)}M`,
  },
  {
    key: "knowledge_upload_bytes",
    label: "Upload allowance",
    format: (n) => `${Math.round(n / (1024 * 1024))} MB`,
  },
];

export function TenantLifecycle({
  tenant,
  onChanged,
}: {
  tenant: AdminTenant;
  onChanged: () => void;
}) {
  return (
    <div className="space-y-4">
      <StatusCard tenant={tenant} onChanged={onChanged} />
      <PlanCard tenant={tenant} onChanged={onChanged} />
      <DangerZone tenant={tenant} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

function StatusCard({ tenant, onChanged }: { tenant: AdminTenant; onChanged: () => void }) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const [confirmSuspend, setConfirmSuspend] = useState(false);
  const suspended = tenant.status === "suspended";

  async function setStatus(status: "active" | "suspended") {
    setBusy(true);
    try {
      await adminTenants.update(tenant.id, { status }, { token });
      toast({ title: status === "suspended" ? "Suspended" : "Reactivated", variant: "success" });
      onChanged();
    } catch (err) {
      toast({ title: "Couldn't update", description: describeError(err), variant: "error" });
    } finally {
      setBusy(false);
      setConfirmSuspend(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Status</CardTitle>
          <CardDescription>
            A suspended tenant&apos;s rep goes silent and every signed-in session in the business is
            revoked.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Badge tone={suspended ? "danger" : "success"}>{tenant.status}</Badge>
          {suspended ? (
            <Button size="sm" disabled={busy} onClick={() => setStatus("active")}>
              Reactivate
            </Button>
          ) : (
            /* Suspend is a customer-visible outage, so it sits in the same
               register as the other things that are: confirmed, and named. */
            <Button
              variant="outline"
              size="sm"
              className="border-danger/50 text-danger"
              disabled={busy}
              onClick={() => setConfirmSuspend(true)}
            >
              Suspend
            </Button>
          )}
        </div>
        {suspended ? (
          <p className="rounded-xl bg-warning/10 px-3 py-2 text-xs text-muted-foreground">
            Suspended. The rep is silent for this tenant until it is reactivated.
          </p>
        ) : null}
      </CardContent>

      <ConfirmByName
        open={confirmSuspend}
        name={tenant.name}
        title="Suspend this business?"
        description={`"${tenant.name}" stops answering customers immediately, and everybody signed in there is signed out. Their data is untouched and you can reactivate at any time.`}
        confirmLabel="Suspend"
        busy={busy}
        onClose={() => setConfirmSuspend(false)}
        onConfirm={() => setStatus("suspended")}
      />
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Plan (F3 / A4)
// ---------------------------------------------------------------------------

function PlanCard({ tenant, onChanged }: { tenant: AdminTenant; onChanged: () => void }) {
  const token = useAuthToken();
  const { toast } = useToast();
  const { data: plans, loading: plansLoading } = useApi(() => adminPlans.list({ token }), [token]);
  const [selected, setSelected] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [trialEnds, setTrialEnds] = useState<string>(
    tenant.trialEndsAt ? tenant.trialEndsAt.slice(0, 10) : "",
  );

  const currentKey = tenant.subscription?.planKey ?? tenant.planKey ?? "";
  const choice = selected || currentKey;
  const chosenPlan = plans?.find((p) => p.key === choice) ?? null;
  const changed = choice !== "" && choice !== currentKey;

  const daysLeft = tenant.trialEndsAt
    ? Math.ceil((new Date(tenant.trialEndsAt).getTime() - Date.now()) / 86_400_000)
    : null;

  async function applyPlan() {
    if (!changed) return;
    setBusy(true);
    try {
      // The one call that matters: the backend rewrites entitlements from the
      // catalogue as part of it, which is what the old toggle never did.
      const sub = await adminSubscription.set(
        tenant.id,
        { planKey: choice, status: choice === "trial" ? "trialing" : "active" },
        { token },
      );
      toast({
        title: `Moved to ${sub.planName}`,
        description: "Entitlements rewritten from the plan catalogue.",
        variant: "success",
      });
      setSelected("");
      onChanged();
    } catch (err) {
      toast({ title: "Couldn't change plan", description: describeError(err), variant: "error" });
    } finally {
      setBusy(false);
    }
  }

  async function saveTrialEnd(value: string) {
    setBusy(true);
    try {
      await adminTenants.update(
        tenant.id,
        // Midday UTC rather than midnight: a trial that expires at 00:00 in the
        // operator's head expires the previous evening for a tenant east of
        // here, and the customer finds out by being cut off a day early.
        { trialEndsAt: value ? new Date(`${value}T12:00:00Z`).toISOString() : null },
        { token },
      );
      toast({ title: "Trial end updated", variant: "success" });
      onChanged();
    } catch (err) {
      toast({ title: "Couldn't update", description: describeError(err), variant: "error" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Plan</CardTitle>
          <CardDescription>
            Picks a plan from the catalogue and rewrites this tenant&apos;s entitlements from it.
            Prices live with the payment provider, never here.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-semibold">Currently</span>
          <Badge tone={tenant.plan === "paid" ? "success" : "default"}>
            {tenant.subscription?.planName ?? (currentKey || tenant.plan)}
          </Badge>
          {tenant.subscription ? (
            <span className="text-xs text-muted-foreground">
              {tenant.subscription.status} · via {tenant.subscription.provider}
              {tenant.subscription.cancelAtPeriodEnd ? " · cancels at period end" : ""}
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">
              no subscription row yet, so the trial defaults apply
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[12rem] space-y-1.5">
            <Label htmlFor="plan-key">Move to</Label>
            {plansLoading ? (
              <Skeleton className="h-9 w-48" />
            ) : (
              <select
                id="plan-key"
                className={SELECT_CLASSES}
                value={choice}
                onChange={(e) => setSelected(e.target.value)}
              >
                <option value="" disabled>
                  Pick a plan
                </option>
                {(plans ?? []).map((plan) => (
                  <option key={plan.key} value={plan.key}>
                    {plan.name}
                    {plan.key === currentKey ? " (current)" : ""}
                  </option>
                ))}
              </select>
            )}
          </div>
          <Button disabled={!changed || busy} onClick={applyPlan}>
            {busy ? "Applying…" : "Apply plan"}
          </Button>
        </div>

        {chosenPlan ? (
          <div className="rounded-xl border border-border bg-surface-muted p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {changed ? `${chosenPlan.name} would grant` : "In force now"}
            </p>
            <dl className="mt-2 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
              {ENTITLEMENT_LABELS.map(({ key, label, format }) => {
                const target = chosenPlan.entitlements[key];
                const live = tenant.entitlements?.[key];
                if (target == null) return null;
                const show = format ? format(target) : target.toLocaleString();
                // The mismatch F3 produced, made visible: a stored allowance
                // that does not match the plan on the row.
                const stale = !changed && live != null && live !== target;
                return (
                  <div key={key} className="flex items-baseline justify-between gap-3">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className={`tabular-nums font-semibold ${stale ? "text-danger" : ""}`}>
                      {stale ? `${format ? format(live) : live.toLocaleString()} (stale)` : show}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </div>
        ) : null}

        {/* Trial clock. The field worked and nothing set it (A4). */}
        <div className="space-y-1.5 border-t border-border pt-4">
          <Label htmlFor="trial-ends">Trial ends</Label>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              id="trial-ends"
              type="date"
              className="h-9 w-44"
              value={trialEnds}
              onChange={(e) => setTrialEnds(e.target.value)}
            />
            <Button
              variant="outline"
              size="sm"
              disabled={busy || (trialEnds || "") === (tenant.trialEndsAt?.slice(0, 10) ?? "")}
              onClick={() => saveTrialEnd(trialEnds)}
            >
              Save date
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => {
                const next = new Date(Date.now() + TRIAL_DAYS * 86_400_000)
                  .toISOString()
                  .slice(0, 10);
                setTrialEnds(next);
                void saveTrialEnd(next);
              }}
            >
              Give another {TRIAL_DAYS} days
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            {tenant.trialEndsAt
              ? `${formatDate(tenant.trialEndsAt)}${
                  daysLeft !== null
                    ? daysLeft > 0
                      ? ` · ${daysLeft} day${daysLeft === 1 ? "" : "s"} left`
                      : " · expired"
                    : ""
                }`
              : "No trial end set."}{" "}
            Extending the clock does not change the plan, and a plan change does not clear the
            clock.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Danger zone
// ---------------------------------------------------------------------------

function DangerZone({ tenant }: { tenant: AdminTenant }) {
  const token = useAuthToken();
  const { toast } = useToast();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function remove() {
    setDeleting(true);
    try {
      await adminTenants.remove(tenant.id, { token });
      toast({ title: "Tenant deleted", variant: "success" });
      router.push("/admin/tenants");
    } catch (err) {
      toast({ title: "Couldn't delete tenant", description: describeError(err), variant: "error" });
      setDeleting(false);
    }
  }

  return (
    <div className="rounded-2xl border border-danger/40 bg-danger/5 p-4">
      <p className="text-sm font-semibold text-danger">Danger zone</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Permanently delete this business and everything in it: sessions, conversations, knowledge,
        uploaded files. This cannot be undone.
      </p>
      <Button
        variant="outline"
        size="sm"
        className="mt-3 border-danger/50 text-danger"
        onClick={() => setOpen(true)}
      >
        Delete tenant
      </Button>

      <ConfirmByName
        open={open}
        name={tenant.name}
        title="Delete tenant"
        description={`This permanently deletes "${tenant.name}" and all its data.`}
        confirmLabel="Delete permanently"
        busy={deleting}
        onClose={() => setOpen(false)}
        onConfirm={remove}
      />
    </div>
  );
}

/**
 * One confirmation shape for everything customer-visible.
 *
 * Delete already demanded the business name; suspend and logout did not, and
 * the difference was not a considered one. Typing the name makes the operator
 * name the customer they are about to affect, which is the check that catches
 * the mistake that actually happens: doing it to the wrong row.
 */
function ConfirmByName({
  open,
  name,
  title,
  description,
  confirmLabel,
  busy,
  onClose,
  onConfirm,
}: {
  open: boolean;
  name: string;
  title: string;
  description: string;
  confirmLabel: string;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const [typed, setTyped] = useState("");

  return (
    <Dialog open={open} onClose={onClose} title={title} description={description}>
      <div className="space-y-4">
        <div className="space-y-1.5">
          <label htmlFor={`confirm-${title}`} className="text-xs font-semibold">
            Type <span className="font-bold text-foreground">{name}</span> to confirm
          </label>
          <Input
            id={`confirm-${title}`}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={name}
            autoComplete="off"
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="danger" disabled={busy || typed !== name} onClick={onConfirm}>
            {busy ? "Working…" : confirmLabel}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
