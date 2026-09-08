"use client";

import { Smartphone } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { VerifyEmailNotice } from "@/components/whatsapp/qr-panel";
import { ApiError, describeError } from "@/lib/api";
import { connections } from "@/lib/api/connections";

/**
 * First-run linking.
 *
 * It asks for nothing when this is the tenant's first number. It used to ask a
 * salon owner to invent a "session name", with the example
 * `main-support-line`, and disabled the button until they did (teardown W2) --
 * that is the WAHA session key, which the API derives from the label anyway.
 *
 * A label is only worth asking about once a tenant genuinely has two numbers to
 * tell apart, and then the question is "which number is this", not "name the
 * session".
 */
export function ConnectCard({
  askLabel,
  token,
  onCreated,
}: {
  askLabel: boolean;
  token: string | undefined;
  onCreated: () => void;
}) {
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unverified, setUnverified] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    setUnverified(null);
    try {
      await connections.create(askLabel ? label : undefined, { token });
      onCreated();
    } catch (err) {
      if (err instanceof ApiError && err.status === 403 && err.detail?.code === "email_unverified") {
        setUnverified(err.detail.message ?? null);
      } else {
        setError(describeError(err, "Couldn't start linking. Please try again."));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardContent className="space-y-4 pt-5">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/15 text-primary-strong">
            <Smartphone className="h-5 w-5" />
          </span>
          <div>
            <p className="text-base font-bold tracking-tight">
              {askLabel ? "Link another number" : "Link your WhatsApp number"}
            </p>
            <p className="text-sm text-muted-foreground">
              You will scan a QR code from the business phone, the same way WhatsApp Web works. It
              stays linked until you unlink it.
            </p>
          </div>
        </div>

        {askLabel ? (
          <div className="max-w-xs space-y-1.5">
            <Label htmlFor="wa-label">Which number is this?</Label>
            <Input
              id="wa-label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Front desk"
            />
            <p className="text-xs text-muted-foreground">
              Just so you can tell them apart. Optional.
            </p>
          </div>
        ) : null}

        {unverified !== null ? (
          <VerifyEmailNotice action="link a WhatsApp number" message={unverified ?? undefined} />
        ) : null}
        {error ? <p className="text-sm text-danger">{error}</p> : null}

        <Button onClick={start} disabled={busy}>
          {busy ? "Starting…" : askLabel ? "Link this number" : "Connect WhatsApp"}
        </Button>
      </CardContent>
    </Card>
  );
}
