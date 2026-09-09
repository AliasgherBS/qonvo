"use client";

import { Smartphone } from "lucide-react";
import Link from "next/link";

import { sessions, type Role, type SessionStatus, type WhatsappSessionStatus } from "@/lib/api";
import { useAuthToken, usePolling } from "@/lib/use-api";

/**
 * Connection watchdog. Polls the tenant's sessions and, when none is WORKING,
 * shows a persistent banner - so a dropped number (or a never-connected one) is
 * impossible to miss. Renders nothing while healthy or still loading, so it
 * never flashes.
 *
 * A staff seat gets the warning without the link. Re-linking a number is
 * owner-only, so the link would bounce them straight back here, but they are
 * usually the person who notices first and the useful thing is for them to tell
 * the owner rather than to be sent nowhere.
 *
 * On finding F4 (a tenant's number FAILED for days with nobody told) this
 * banner was verified to be the one surface that did fire: it is mounted in the
 * dashboard layout, `GET /api/sessions` returns the status the health poll
 * writes, and FAILED is not WORKING. What it did not do was distinguish the
 * cases, and they need different words:
 *
 * - FAILED: the connection is dead. The rep is answering nobody, now.
 * - SCAN_QR_CODE: WhatsApp logged the number out. Only a phone can fix it.
 * - STOPPED: it is switched off.
 * - STARTING: it is reconnecting by itself. Saying "disconnected" here is how a
 *   banner trains an owner to ignore it, so this one is calm and neutral.
 * - nothing at all: onboarding, not an outage.
 *
 * The owner-facing alerting for the same event now lives in the scheduler
 * (notification + email within minutes). This is the in-product half, and it
 * says the same thing, because two surfaces disagreeing about whether the rep
 * is answering is worse than either one being terse.
 */

type Severity = "down" | "pending" | "reconnecting";

function severityOf(statuses: SessionStatus[]): Severity {
  if (statuses.includes("STARTING")) return "reconnecting";
  if (statuses.includes("FAILED") || statuses.includes("STOPPED")) return "down";
  // SCAN_QR_CODE, or a status this build does not know about yet.
  return "pending";
}

export function ConnectionBanner({ role }: { role: Role }) {
  const token = useAuthToken();
  const { data } = usePolling<WhatsappSessionStatus[]>(
    () => sessions.list({ token }),
    30_000,
    [token],
  );

  if (!data) return null;
  if (data.some((s) => s.status === "WORKING")) return null;

  const hasSession = data.length > 0;
  const severity = hasSession ? severityOf(data.map((s) => s.status)) : "pending";
  const reconnecting = severity === "reconnecting";

  const tone = reconnecting
    ? "border-border-strong bg-surface-muted"
    : severity === "down"
      ? "border-danger/40 bg-danger/10"
      : "border-warning/40 bg-warning/10";
  const shell = `mb-4 flex items-center gap-3 rounded-2xl border px-4 py-3 text-sm font-semibold text-foreground ${tone}`;

  const icon = (
    <span
      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
        reconnecting
          ? "bg-border text-muted-foreground"
          : severity === "down"
            ? "bg-danger/20 text-danger"
            : "bg-warning/20 text-warning-strong"
      }`}
    >
      <Smartphone className="h-4 w-4" />
    </span>
  );

  // Mid-reconnect is not an outage yet, and it resolves on its own within a
  // minute or two. Nobody is asked to do anything.
  if (reconnecting) {
    return (
      <div className={shell}>
        {icon}
        <span>Reconnecting your WhatsApp number. Replies resume as soon as it is back.</span>
      </div>
    );
  }

  const staffText = !hasSession
    ? "No WhatsApp number is connected yet, so the rep is not replying. The owner can connect one."
    : severity === "down"
      ? "The WhatsApp number is disconnected, so your rep is not replying to anyone. Ask the owner to reconnect it."
      : "WhatsApp has logged the number out, so your rep is not replying. Ask the owner to scan the QR code again.";

  if (role !== "owner") {
    return (
      <div className={shell}>
        {icon}
        <span>{staffText}</span>
      </div>
    );
  }

  const ownerText = !hasSession
    ? "Connect your WhatsApp number to start receiving messages."
    : severity === "down"
      ? "Your WhatsApp number is disconnected, so your rep is not replying and customers are getting no answer. Reconnect it now."
      : "WhatsApp has logged your number out, so your rep is not replying. Scan the QR code again to bring it back.";

  return (
    <Link
      href="/onboarding/connect"
      className={`${shell} transition-opacity hover:opacity-90`}
    >
      {icon}
      <span>
        {ownerText}
        <span className="ml-1 underline">Open connect →</span>
      </span>
    </Link>
  );
}
