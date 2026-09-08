"use client";

import { AlertTriangle, Check, Loader2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import { activation, describeError, type Activation } from "@/lib/api";
import { useAuthToken } from "@/lib/use-api";

/**
 * The rep's account-level on/off switch, in the top bar (teardown S3).
 *
 * Putting it on every page was right: the case it exists for is urgent, and
 * hunting for it is the failure. Rendering it as a full-width card above the
 * content was not. It pushed every H1 ninety pixels down the page on desktop
 * and ate a hundred and thirty pixels of the first screen on a phone, on all
 * thirteen pages, so something needed occasionally had taken the position of
 * something needed constantly.
 *
 * Still global, still one click. The switch itself toggles on the first click
 * with no confirmation, which is deliberate for the same reason it used to be
 * a card: an owner who wants their number back wants it now.
 *
 * When the rep is off the label says so plainly rather than "paused", because
 * the thing an owner needs to know is that messages still arrive and are
 * theirs to answer. That sentence, and the readiness gaps, moved into a
 * popover: they are worth reading once, not on every page load.
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
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setState(await activation.get({ token }));
    } catch {
      // Silent: this is a status control, and a failed read must not become a
      // toast on every page load.
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function toggle(next: boolean) {
    if (!token || !state) return;
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
    <div ref={ref} data-tour="rep-switch" className="relative flex items-center gap-2">
      <Switch
        checked={state.repActive}
        disabled={saving}
        onCheckedChange={toggle}
        label={state.repActive ? "Pause my rep" : "Turn my rep on"}
      />

      {/* The state in words as well as in the switch's position. A lone toggle
          in a top bar is ambiguous about which way is on. */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="dialog"
        className="flex items-center gap-1.5 text-xs font-bold text-foreground"
      >
        {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
        <span className="hidden sm:inline">{state.repActive ? "Rep on" : "Rep paused"}</span>
        {/* On a phone the words are dropped and only the dot carries the state,
            so it has to differ by more than colour. */}
        <span className="sm:hidden">{state.repActive ? "On" : "Off"}</span>
        {missing.length > 0 ? (
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" />
        ) : null}
      </button>

      {open ? (
        <div
          role="dialog"
          aria-label="Your rep"
          className="absolute right-0 top-full z-30 mt-2 w-72 rounded-2xl border border-border bg-surface p-4 shadow-xl"
        >
          <p className="text-sm font-bold">
            {state.repActive ? "Rep is answering" : "Rep is paused"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {state.repActive
              ? "Customers who message your number get a reply."
              : "Messages still arrive in your inbox. You answer them yourself until you switch this back on."}
          </p>

          {/* Advisory only. Listed while off so the owner can see what would
              make the rep useful, and listed while on because switching on
              early is allowed and the gaps do not stop mattering. */}
          {missing.length > 0 ? (
            <div className="mt-3 border-t border-border pt-3">
              <p className="flex items-center gap-2 text-xs font-semibold">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" />
                {state.repActive
                  ? "It will not know much yet"
                  : "Worth doing before you turn it on"}
              </p>
              <ul className="mt-2 space-y-1">
                {missing.map((item) => (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={() => setOpen(false)}
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
      ) : null}
    </div>
  );
}
