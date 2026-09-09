"use client";

import { useEffect, useState } from "react";

import { ApiError, sessions } from "@/lib/api";

const QR_REFRESH_MS = 15_000;

/**
 * The pairing QR, fetched as an authenticated blob.
 *
 * It cannot be an `<img src>`: the endpoint requires a bearer token, an `<img>`
 * tag sends none, and the QR would never render. So fetch it with the token,
 * wrap it in an object URL, and refresh every 15s (the code expires in about
 * 20), revoking the previous URL each cycle.
 */
export function QrPanel({ sessionName, token }: { sessionName: string; token: string | undefined }) {
  const [qrUrl, setQrUrl] = useState<string | null>(null);
  const [blocked, setBlocked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;

    const load = async () => {
      try {
        const blob = await sessions.qrBlob(sessionName, { token });
        if (cancelled) return;
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        objectUrl = URL.createObjectURL(blob);
        setQrUrl(objectUrl);
        setBlocked(false);
      } catch (err) {
        // A 403 here is not transient and not a bug. The QR route is gated on a
        // confirmed owner, and this page is owner-only, so the only way to be
        // refused is an unconfirmed address -- worth saying, rather than
        // spinning on a skeleton forever.
        if (!cancelled && err instanceof ApiError && err.status === 403) setBlocked(true);
        // Anything else is transient (token not hydrated, QR rotating): retry.
      }
    };

    void load();
    const id = window.setInterval(load, QR_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [sessionName, token]);

  if (blocked) {
    return <VerifyEmailNotice action="show the pairing code" />;
  }

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="flex h-56 w-56 items-center justify-center overflow-hidden rounded-2xl border border-border bg-surface-muted">
        {qrUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={qrUrl}
            alt="Scan this QR code with WhatsApp to link the device"
            className="h-full w-full object-contain"
          />
        ) : (
          <div className="h-full w-full animate-pulse bg-surface-muted" />
        )}
      </div>
      <ol className="max-w-xs list-inside list-decimal space-y-1 text-left text-xs text-muted-foreground">
        <li>Open WhatsApp on the business phone.</li>
        <li>Tap Settings, then Linked devices.</li>
        <li>Tap Link a device and scan this code.</li>
      </ol>
      <p className="text-xs text-muted-foreground">Refreshes automatically every 15s</p>
    </div>
  );
}

/**
 * The real reason a connect or QR call was refused.
 *
 * `require_verified_owner` answers 403 with `{"code": "email_unverified"}`, and
 * showing "You don't have permission to do that" for it sends the owner looking
 * for a permissions setting that does not exist.
 */
export function VerifyEmailNotice({ action, message }: { action: string; message?: string }) {
  return (
    <div className="rounded-2xl border border-warning/40 bg-warning/10 px-4 py-3 text-left text-sm">
      <p className="font-semibold">Confirm your email first</p>
      <p className="mt-0.5 text-muted-foreground">
        {message ??
          `We need a confirmed address before we ${action}. Check your inbox for the link we sent when you signed up.`}
      </p>
    </div>
  );
}
