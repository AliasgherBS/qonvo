"use client";

import { AlertTriangle, Bot, Check, Loader2, PauseCircle } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { activation, describeError, type Activation } from "@/lib/api";
import { useAuthToken } from "@/lib/use-api";

/**
 * The rep's account-level on/off switch.
 *
 * A first-class control rather than a settings row, because the case it exists
 * for is urgent: the owner wants their number back, now. Anything between them
 * and that, a modal or a settings page two clicks away, is the wrong side of
 * the trade.
 *
 * When the rep is off it says what still happens, because "paused" on its own
 * reads like the product broke. Messages still arrive; the owner answers them.
 *
 * Readiness is shown, never enforced. Switching on with an empty knowledge base
 * produces a rep that says it does not know most answers, which is worth
 * warning about and is not ours to forbid.
 */
export function RepSwitch() {
  const token = useAuthToken();
  const { toast } = useToast();
  const [state, setState] = useState<Activation | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setState(await activation.get({ token }));
    } catch {
      // Silent: this is a status card, and a failed read must not become a
      // toast on every page load.
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggle() {
    if (!token || !state) return;
    const next = !state.repActive;
    setSaving(true);
    try {
      setState(await activation.set(next, { token }));
      toast({
        title: next ? "Your rep is answering" : "Your rep is paused",
        description: next
          ? "New messages get a reply."
          : "Messages still arrive in your inbox. You answer them.",
        variant: "success",
      });
    } catch (err) {
      toast({ title: "Could not change this", description: describeError(err), variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  if (!state) return null;

  const missing = [
    !state.readiness.whatsappConnected && {
      label: "Connect your WhatsApp number",
      href: "/onboarding/connect",
    },
    !state.readiness.hasGrounding && {
      label: "Add what your rep should know",
      href: "/knowledge",
    },
    !state.readiness.businessNameSet && {
      label: "Set your business name",
      href: "/business",
    },
  ].filter(Boolean) as { label: string; href: string }[];

  return (
    <div className="mb-4 rounded-2xl border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          {state.repActive ? (
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/15">
              <Bot className="h-5 w-5 text-primary-strong" />
            </span>
          ) : (
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-warning/15">
              <PauseCircle className="h-5 w-5 text-warning" />
            </span>
          )}
          <div>
            <p className="text-sm font-bold">
              {state.repActive ? "Rep is answering" : "Rep is paused"}
            </p>
            <p className="text-xs text-muted-foreground">
              {state.repActive
                ? "Customers who message your number get a reply."
                : "Messages still arrive in your inbox. You answer them yourself until you switch this back on."}
            </p>
          </div>
        </div>

        <Button
          onClick={toggle}
          disabled={saving}
          variant={state.repActive ? "outline" : "primary"}
        >
          {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
          {state.repActive ? "Pause my rep" : "Turn my rep on"}
        </Button>
      </div>

      {/* Advisory only. Listed while off so the owner can see what would make
          the rep useful, and listed while on because switching on early is
          allowed and the gaps do not stop mattering. */}
      {missing.length > 0 ? (
        <div className="mt-3 border-t border-border pt-3">
          <p className="flex items-center gap-2 text-xs font-semibold">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" />
            {state.repActive
              ? "Your rep is answering, but it will not know much yet"
              : "Worth doing before you turn it on"}
          </p>
          <ul className="mt-2 space-y-1">
            {missing.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="text-xs font-semibold text-primary-strong underline-offset-2 hover:underline"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : !state.repActive ? (
        <p className="mt-3 flex items-center gap-2 border-t border-border pt-3 text-xs text-muted-foreground">
          <Check className="h-3.5 w-3.5 shrink-0 text-primary-strong" />
          Everything is set up. Turn your rep on whenever you are ready.
        </p>
      ) : null}
    </div>
  );
}
