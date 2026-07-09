"use client";

import { CheckCircle2, QrCode, RefreshCw, Smartphone } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { sessions, type SessionStatus, type WhatsappSessionStatus } from "@/lib/api";
import { useAuthToken, usePolling } from "@/lib/use-api";

const STATUS_COPY: Record<SessionStatus, { title: string; description: string }> = {
  STOPPED: {
    title: "Not connected",
    description: "Start the session to generate a QR code.",
  },
  STARTING: {
    title: "Starting up…",
    description: "Spinning up your WhatsApp session — this only takes a moment.",
  },
  SCAN_QR_CODE: {
    title: "Scan to connect",
    description: "Open WhatsApp on the business phone → Linked devices → Link a device.",
  },
  WORKING: {
    title: "Connected",
    description: "This number is live — Qonvo is watching for new messages.",
  },
  FAILED: {
    title: "Connection failed",
    description: "Something went wrong linking this number. Try again with a new session.",
  },
};

const QR_REFRESH_MS = 15_000;
const STATUS_POLL_MS = 5_000;

export default function ConnectPage() {
  const token = useAuthToken();
  const [sessionName, setSessionName] = useState("");
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  async function handleStart() {
    if (!sessionName.trim()) return;
    setStarting(true);
    setStartError(null);
    try {
      await sessions.create({ name: sessionName.trim(), label: sessionName.trim() }, { token });
      setActiveSession(sessionName.trim());
    } catch {
      setStartError("Couldn't reach the backend yet — this will start the moment the sessions API is live.");
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Connect your WhatsApp number</h1>
        <p className="text-sm text-muted-foreground">
          Never miss a customer — link the business number Qonvo should watch.
        </p>
      </div>

      {!activeSession ? (
        <Card>
          <CardContent className="space-y-4 pt-5">
            <div className="space-y-1.5">
              <Label htmlFor="session-name">Session name</Label>
              <Input
                id="session-name"
                value={sessionName}
                onChange={(e) => setSessionName(e.target.value)}
                placeholder="e.g. main-support-line"
              />
            </div>
            {startError ? <p className="text-sm text-danger">{startError}</p> : null}
            <Button onClick={handleStart} disabled={starting || !sessionName.trim()} className="w-full">
              {starting ? "Starting…" : "Start connecting"}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <QrFlow sessionName={activeSession} onRetry={() => setActiveSession(null)} />
      )}
    </div>
  );
}

function QrFlow({ sessionName, onRetry }: { sessionName: string; onRetry: () => void }) {
  const token = useAuthToken();
  const { data: session, error } = usePolling<WhatsappSessionStatus>(
    () => sessions.status(sessionName, { token }),
    STATUS_POLL_MS,
    [sessionName, token],
  );

  const status = session?.status ?? "STARTING";
  const copy = STATUS_COPY[status];
  const showQr = status === "SCAN_QR_CODE";

  const [qrNonce, setQrNonce] = useState(0);

  useEffect(() => {
    if (!showQr) return;
    const id = window.setInterval(() => setQrNonce((n) => n + 1), QR_REFRESH_MS);
    return () => window.clearInterval(id);
  }, [showQr]);

  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 pt-5 text-center">
        <StatusIcon status={status} />
        <div>
          <p className="text-lg font-bold tracking-tight">{copy.title}</p>
          <p className="text-sm text-muted-foreground">{copy.description}</p>
        </div>

        {showQr ? (
          <div className="flex flex-col items-center gap-2">
            <div className="flex h-56 w-56 items-center justify-center overflow-hidden rounded-2xl border border-border bg-surface-muted">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                key={qrNonce}
                src={`${sessions.qrImageUrl(sessionName)}?t=${qrNonce}`}
                alt="Scan this QR code with WhatsApp to link the device"
                className="h-full w-full object-contain"
                onError={(e) => {
                  e.currentTarget.style.display = "none";
                }}
              />
            </div>
            <p className="text-xs text-muted-foreground">Refreshes automatically every 15s</p>
          </div>
        ) : null}

        {status === "STARTING" || status === "STOPPED" ? (
          <div className="h-56 w-56 animate-pulse rounded-2xl bg-surface-muted" />
        ) : null}

        {status === "WORKING" ? (
          <div className="rounded-full bg-primary/15 px-4 py-2 text-sm font-semibold text-primary-strong">
            Live and watching for messages
          </div>
        ) : null}

        {status === "FAILED" ? (
          <Button variant="outline" onClick={onRetry}>
            <RefreshCw className="h-4 w-4" />
            Try again
          </Button>
        ) : null}

        {error ? (
          <p className="text-xs text-muted-foreground">
            Waiting on the sessions API — status will update automatically once it&apos;s reachable.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function StatusIcon({ status }: { status: SessionStatus }) {
  const className = "h-8 w-8";
  switch (status) {
    case "WORKING":
      return <CheckCircle2 className={`${className} text-primary`} />;
    case "SCAN_QR_CODE":
      return <QrCode className={className} />;
    case "FAILED":
      return <Smartphone className={`${className} text-danger`} />;
    default:
      return <Smartphone className={`${className} text-muted-foreground`} />;
  }
}
