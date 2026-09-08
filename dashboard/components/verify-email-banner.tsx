"use client";

import { MailWarning } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { auth, describeError } from "@/lib/api";
import { useAuthToken } from "@/lib/use-api";

/**
 * Says the address is unconfirmed, and offers another link (teardown X2).
 *
 * Reads `/api/me` rather than the session, deliberately. The session is minted
 * at sign-in and would keep saying "unconfirmed" for its whole lifetime after
 * somebody confirmed in another tab, so the banner would outlive the problem it
 * describes. This is also why the gate on the API reads the database instead of
 * a claim in the token.
 *
 * Names the consequence rather than just asking. "Please verify your email"
 * with nothing attached is the kind of banner people learn to look past; the
 * thing they actually need to know is that the number will not link until they
 * do.
 */
export function VerifyEmailBanner() {
  const token = useAuthToken();
  const { toast } = useToast();
  const [unverified, setUnverified] = useState(false);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const me = await auth.me({ token });
      setUnverified(!me.emailVerified);
    } catch {
      // Silent. A failed read here must not become a toast on every page load,
      // and the safe assumption is that there is nothing to nag about.
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!unverified) return null;

  async function resend() {
    setSending(true);
    try {
      await auth.resendVerification({ token });
      setSent(true);
      toast({ title: "Confirmation link sent", variant: "success" });
    } catch (err) {
      toast({ title: "Could not send it", description: describeError(err), variant: "error" });
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="mb-4 flex flex-wrap items-center gap-3 rounded-2xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm font-semibold text-foreground">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-warning/20 text-warning-strong">
        <MailWarning className="h-4 w-4" />
      </span>
      <span className="flex-1">
        Confirm your email address to connect your WhatsApp number. Check your inbox for the link
        we sent when you signed up.
      </span>
      <Button variant="outline" size="sm" disabled={sending || sent} onClick={resend}>
        {sent ? "Link sent" : sending ? "Sending…" : "Send it again"}
      </Button>
    </div>
  );
}
