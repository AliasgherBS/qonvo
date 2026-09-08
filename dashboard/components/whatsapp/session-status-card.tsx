"use client";

import { AlertTriangle, CheckCircle2, QrCode, RefreshCw, Smartphone, Unlink } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { QrPanel } from "@/components/whatsapp/qr-panel";
import { ApiError, describeError, type SessionStatus } from "@/lib/api";
import { connections, type WhatsappSession, type WhatsappSessionLive } from "@/lib/api/connections";
import { formatDate, formatRelative } from "@/lib/format";
import { usePolling } from "@/lib/use-api";

const STATUS_POLL_MS = 5_000;

interface StateCopy {
  label: string;
  tone: "default" | "success" | "warning" | "danger";
  headline: string;
  detail: string;
}

/**
 * What each WAHA state means to a business owner, not to an operator.
 *
 * "STOPPED" and "FAILED" both mean "your rep is not answering right now", which
 * is the sentence that matters, and neither of them used to appear anywhere the
 * owner could see (teardown W1).
 */
const STATE: Record<SessionStatus, StateCopy> = {
  WORKING: {
    label: "Connected",
    tone: "success",
    headline: "Your rep is answering on this number",
    detail: "Qonvo is watching for new messages and replying 24/7.",
  },
  STARTING: {
    label: "Starting",
    tone: "default",
    headline: "Starting up",
    detail: "Reconnecting to WhatsApp. This usually takes a few seconds.",
  },
  SCAN_QR_CODE: {
    label: "Needs re-linking",
    tone: "warning",
    headline: "Scan to link this number",
    detail: "WhatsApp needs the code below scanned from the business phone.",
  },
  STOPPED: {
    label: "Stopped",
    tone: "warning",
    headline: "This number is not being watched",
    detail: "Nobody is answering incoming messages. Restart to bring it back.",
  },
  FAILED: {
    label: "Disconnected",
    tone: "danger",
    headline: "WhatsApp dropped this session",
    detail:
      "Sessions drop on a phone reboot or a logout from the phone. Restart first; re-link if that does not bring it back.",
  },
};

/** Digits as WhatsApp reports them, with the leading plus it omits. */
function formatWaNumber(digits: string | null): string | null {
  if (!digits) return null;
  return digits.startsWith("+") ? digits : `+${digits}`;
}

export function SessionStatusCard({
  session,
  onChanged,
  token,
}: {
  session: WhatsappSession;
  onChanged: () => void;
  token: string | undefined;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmRelink, setConfirmRelink] = useState(false);

  // Poll the live status so a session that drops while the owner is looking at
  // the page says so, rather than showing the last-known state until a reload.
  const { data: live, error } = usePolling<WhatsappSessionLive>(
    () => connections.live(session.name, { token }),
    STATUS_POLL_MS,
    [session.name, token],
  );

  const status = live?.status ?? session.status;
  const copy = STATE[status];
  const number = formatWaNumber(live?.phoneNumber ?? session.phoneNumber);
  const lastEventAt = live?.lastEventAt ?? session.lastEventAt;
  const connectedAt = live?.connectedAt ?? session.connectedAt;
  const label = live?.label ?? session.label;

  async function act(
    key: "restart" | "logout",
    fn: () => Promise<unknown>,
    successTitle: string,
  ) {
    setBusy(key);
    try {
      await fn();
      toast({ title: successTitle, variant: "success" });
      onChanged();
    } catch (err) {
      // The verified-owner gate answers 403 with a code, and "you don't have
      // permission" would send an owner hunting for a setting.
      const unverified =
        err instanceof ApiError && err.status === 403 && err.detail?.code === "email_unverified";
      toast({
        title: unverified ? "Confirm your email first" : "That didn't work",
        description: unverified
          ? err.detail?.message ?? "Check your inbox for the confirmation link."
          : describeError(err),
        variant: "error",
      });
    } finally {
      setBusy(null);
      setConfirmRelink(false);
    }
  }

  return (
    <Card>
      <CardContent className="space-y-5 pt-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/15 text-primary-strong">
              <StatusIcon status={status} />
            </span>
            <div>
              <p className="text-lg font-bold tracking-tight">
                {number ?? label ?? "WhatsApp number"}
              </p>
              <p className="text-sm text-muted-foreground">
                {number && label ? label : copy.headline}
              </p>
            </div>
          </div>
          <Badge tone={copy.tone}>{copy.label}</Badge>
        </div>

        {status !== "WORKING" ? (
          <div className="flex items-start gap-3 rounded-2xl border border-border bg-surface-muted px-4 py-3 text-sm">
            {copy.tone === "danger" || copy.tone === "warning" ? (
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            ) : null}
            <div>
              <p className="font-semibold">{copy.headline}</p>
              <p className="mt-0.5 text-muted-foreground">{copy.detail}</p>
            </div>
          </div>
        ) : null}

        <dl className="grid gap-4 sm:grid-cols-3">
          <Fact term="Number">{number ?? "Not reported yet"}</Fact>
          <Fact term="Linked">{formatDate(connectedAt)}</Fact>
          {/* The number is the product, so "has anything arrived on it lately"
              is the question this page exists to answer. */}
          <Fact term="Last message">
            {lastEventAt ? formatRelative(lastEventAt) : "No messages yet"}
          </Fact>
        </dl>

        {status === "SCAN_QR_CODE" ? (
          <div className="flex justify-center">
            <QrPanel sessionName={session.name} token={token} />
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4">
          <Button
            variant={status === "WORKING" ? "outline" : "primary"}
            size="sm"
            disabled={busy !== null}
            onClick={() =>
              act("restart", () => connections.restart(session.name, { token }), "Restarting")
            }
          >
            <RefreshCw className="h-4 w-4" />
            {busy === "restart" ? "Restarting…" : "Restart"}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy !== null}
            onClick={() => setConfirmRelink(true)}
          >
            <Unlink className="h-4 w-4" />
            Re-link this number
          </Button>
          {error ? (
            <span className="ml-auto text-xs text-muted-foreground">
              Live status is unavailable right now. Showing the last known state.
            </span>
          ) : null}
        </div>
      </CardContent>

      <Dialog
        open={confirmRelink}
        onClose={() => setConfirmRelink(false)}
        title="Re-link this number?"
        description="Qonvo logs out of WhatsApp and shows a fresh QR code. Your rep stops answering until somebody scans it from the business phone."
      >
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => setConfirmRelink(false)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            size="sm"
            disabled={busy !== null}
            onClick={() =>
              act("logout", () => connections.logout(session.name, { token }), "Logged out of WhatsApp")
            }
          >
            {busy === "logout" ? "Logging out…" : "Log out and show a QR"}
          </Button>
        </div>
      </Dialog>
    </Card>
  );
}

function Fact({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {term}
      </dt>
      <dd className="mt-0.5 text-sm font-medium">{children}</dd>
    </div>
  );
}

function StatusIcon({ status }: { status: SessionStatus }) {
  const className = "h-5 w-5";
  switch (status) {
    case "WORKING":
      return <CheckCircle2 className={className} />;
    case "SCAN_QR_CODE":
      return <QrCode className={className} />;
    default:
      return <Smartphone className={className} />;
  }
}
