"use client";

import { Check, Copy, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { TotpQr } from "@/components/account/totp-qr";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { ApiError, describeError } from "@/lib/api";
import { profile, security, type TotpEnrolment } from "@/lib/api/account";
import { CONTACT } from "@/lib/contact";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * Two-factor enrolment (teardown V6).
 *
 * The endpoints, the RFC 6238 verification and the replay protection all
 * shipped with the security work; there was simply no way for a person to
 * switch it on, so nobody had. This is that way.
 *
 * **Scan, with typing as the fallback.** An earlier version of this offered
 * only the key, on the grounds that the CSP allows scripts from four CDNs and
 * none of them carries a QR library. That confused two things: the CSP governs
 * scripts fetched at runtime from another origin, not an npm dependency, which
 * the build compiles into our own bundle and serves under `'self'`. A
 * 32-character key typed off a screen is the step people abandon, and an
 * authenticator nobody sets up protects nothing.
 *
 * The key stays visible next to the code rather than behind a disclosure,
 * because a camera fails often enough that the alternative has to be one
 * glance away. Grouped in fours: it is transcribed by a human, and twenty-six
 * unbroken characters is where transcription errors come from.
 */
function grouped(secret: string): string {
  return (secret.match(/.{1,4}/g) ?? [secret]).join(" ");
}

export function TwoFactorCard() {
  const token = useAuthToken();
  const { data, loading, refetch } = useApi(() => profile.get({ token }), [token]);
  const { toast } = useToast();

  const [enrolment, setEnrolment] = useState<TotpEnrolment | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  // The disable flow asks for a code too, so a stolen session cannot remove
  // the protection that would have made the session hard to steal.
  const [disabling, setDisabling] = useState(false);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      setEnrolment(await security.startTotp({ token }));
      setCode("");
    } catch (err) {
      if (err instanceof ApiError && err.detail?.code === "totp_already_enabled") {
        // Somebody enrolled in another tab. Re-read rather than argue.
        refetch();
      } else {
        setError(describeError(err, "Could not start the setup."));
      }
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await security.confirmTotp(code.trim(), { token });
      setEnrolment(null);
      setCode("");
      refetch();
      toast({
        title: "Two-factor is on",
        description: "You will be asked for a code the next time you sign in.",
        variant: "success",
      });
    } catch (err) {
      const detail = err instanceof ApiError ? err.detail?.code : undefined;
      setError(
        detail === "totp_not_started"
          ? "That setup expired. Start it again."
          : describeError(err, "That code is not right."),
      );
      if (detail === "totp_not_started") setEnrolment(null);
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    setBusy(true);
    setError(null);
    try {
      await security.disableTotp(code.trim(), { token });
      setDisabling(false);
      setCode("");
      refetch();
      toast({ title: "Two-factor is off", variant: "success" });
    } catch (err) {
      setError(describeError(err, "That code is not right."));
    } finally {
      setBusy(false);
    }
  }

  async function copySecret() {
    if (!enrolment) return;
    try {
      await navigator.clipboard.writeText(enrolment.secret);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard is blocked in some browsers without a user gesture chain, or
      // over plain http. The key is on screen and selectable either way, so
      // this is not worth an error message.
    }
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Two-factor authentication</CardTitle>
          <CardDescription>
            A six-digit code from an app on your phone, on top of your password.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading ? (
          <Skeleton className="h-10 w-48" />
        ) : data?.totpEnabled ? (
          <>
            <p className="flex items-center gap-2 text-sm font-semibold">
              <ShieldCheck className="h-4 w-4 shrink-0 text-primary-strong" />
              On for {data.email}
            </p>
            {disabling ? (
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label htmlFor="totp-disable-code">Enter a current code to turn it off</Label>
                  <Input
                    id="totp-disable-code"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    placeholder="123456"
                    className="max-w-40"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <Button onClick={disable} disabled={busy || code.trim().length < 6}>
                    {busy ? "Checking" : "Turn off"}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setDisabling(false);
                      setCode("");
                      setError(null);
                    }}
                  >
                    Keep it on
                  </Button>
                </div>
              </div>
            ) : (
              <Button variant="outline" onClick={() => setDisabling(true)}>
                Turn off two-factor
              </Button>
            )}
          </>
        ) : enrolment ? (
          <div className="space-y-4">
            <ol className="space-y-3 text-sm">
              <li>
                <span className="font-semibold">1. Open your authenticator app</span>
                <span className="block text-xs text-muted-foreground">
                  Google Authenticator, Authy, 1Password, or whichever you already use, and
                  choose to add an account by scanning.
                </span>
              </li>
              <li>
                <span className="font-semibold">2. Scan this</span>
                <div className="mt-2 flex flex-col gap-4 sm:flex-row sm:items-start">
                  <TotpQr uri={enrolment.provisioningUri} />
                  <div className="min-w-0 space-y-2">
                    <p className="text-xs text-muted-foreground">
                      Cannot scan it? Choose &quot;enter a setup key&quot; in your app and type
                      this instead.
                    </p>
                    <div className="flex flex-wrap items-center gap-2">
                      <code className="select-all rounded-xl border border-border-strong bg-surface-muted px-3 py-2 font-mono text-sm tracking-wider">
                        {grouped(enrolment.secret)}
                      </code>
                      <Button variant="outline" size="sm" onClick={copySecret}>
                        {copied ? (
                          <Check className="mr-1.5 h-3.5 w-3.5" />
                        ) : (
                          <Copy className="mr-1.5 h-3.5 w-3.5" />
                        )}
                        {copied ? "Copied" : "Copy key"}
                      </Button>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Reading this on the phone itself?{" "}
                      <a
                        href={enrolment.provisioningUri}
                        className="font-semibold text-primary-strong underline-offset-2 hover:underline"
                      >
                        Open it in your authenticator app
                      </a>
                      , which beats scanning your own screen.
                    </p>
                  </div>
                </div>
              </li>
              <li>
                <span className="font-semibold">3. Type the code it shows</span>
              </li>
            </ol>

            <div className="space-y-1.5">
              <Label htmlFor="totp-code">Code from your app</Label>
              <Input
                id="totp-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="123456"
                className="max-w-40"
              />
            </div>

            {/* Said before it is switched on, not after. There are no recovery
                codes in the product yet, so losing the app means asking a
                human, and somebody deciding whether to enrol deserves to know
                that while they can still decide. */}
            <p className="rounded-xl bg-surface-muted px-3 py-2 text-xs text-muted-foreground">
              Keep the key somewhere safe. If you lose the app there is no self-serve way back in:
              you would have to email{" "}
              <a
                href={CONTACT.supportHref}
                className="font-semibold text-primary-strong underline-offset-2 hover:underline"
              >
                {CONTACT.support}
              </a>
              .
            </p>

            <div className="flex items-center gap-2">
              <Button onClick={confirm} disabled={busy || code.trim().length < 6}>
                {busy ? "Checking" : "Turn on two-factor"}
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setEnrolment(null);
                  setCode("");
                  setError(null);
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <>
            <p className="text-sm text-muted-foreground">
              Off. Your password on its own is all anyone needs to sign in as you.
            </p>
            <Button onClick={start} disabled={busy}>
              {busy ? "Starting" : "Turn on two-factor"}
            </Button>
          </>
        )}

        {error ? (
          <p role="alert" className="rounded-xl bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
