"use client";

import { signOut } from "next-auth/react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { describeError } from "@/lib/api";
import { security } from "@/lib/api/account";
import { CONTACT } from "@/lib/contact";
import { useAuthToken } from "@/lib/use-api";

/**
 * Signing out everywhere, and being honest about what we cannot show (V6).
 *
 * "Sign out everywhere" is the control a person reaches for the moment they
 * suspect something is wrong, and it was missing from the Account page
 * entirely even though the endpoint shipped with the revocation work.
 *
 * There is deliberately **no list of active sessions**. Sessions are stateless
 * JWTs with a Redis denylist, so there is nothing to enumerate: we know which
 * tokens have been revoked, not which are in use, and no device, city or
 * last-seen time is recorded anywhere. A list assembled from what we do hold
 * would be a guess dressed as a security record, on the one screen where
 * somebody is deciding whether they have been broken into. Saying so is worth
 * more than showing one row that reads "this device".
 */
export function SessionsCard() {
  const token = useAuthToken();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);

  /**
   * Revoke first, then drop the cookie, and await the revoke: `signOut`
   * navigates, and a request that has been started but not awaited is
   * cancelled by the navigation. That would leave a browser that looks signed
   * out holding tokens that still work, on every device, which is the opposite
   * of what the button promises.
   *
   * This one signs the current device out too, and that is the point: an owner
   * who has lost a phone wants every session gone, and being asked to sign in
   * again here is the confirmation that it worked.
   */
  async function signOutEverywhere() {
    setBusy(true);
    try {
      await security.logoutEverywhere({ token });
    } catch (err) {
      toast({ title: "Could not do that", description: describeError(err), variant: "error" });
      setBusy(false);
      return;
    }
    await signOut({ callbackUrl: "/login" });
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Devices</CardTitle>
          <CardDescription>
            Signed in somewhere you should not be? End every session, including this one.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <Button variant="outline" onClick={signOutEverywhere} disabled={busy}>
          {busy ? "Signing out" : "Sign out everywhere"}
        </Button>
        <p className="text-xs text-muted-foreground">
          We do not keep a list of your devices, so there is nothing here to show you: sessions are
          signed tokens, and no device or location is ever recorded. Signing out everywhere is the
          control that works regardless.
        </p>
        <p className="text-xs text-muted-foreground">
          Need your workspace deleted? A person handles that, so it cannot happen by accident.
          Email{" "}
          <a
            href={CONTACT.supportHref}
            className="font-semibold text-primary-strong underline-offset-2 hover:underline"
          >
            {CONTACT.support}
          </a>{" "}
          and we will confirm before anything is removed.
        </p>
      </CardContent>
    </Card>
  );
}
