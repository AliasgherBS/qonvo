"use client";

import { Smartphone } from "lucide-react";
import Link from "next/link";

import { sessions, type WhatsappSessionStatus } from "@/lib/api";
import { useAuthToken, usePolling } from "@/lib/use-api";

/**
 * Owner-facing connection watchdog. Polls the tenant's sessions and, when none
 * is WORKING, shows a persistent banner linking to the connect flow — so a
 * dropped number (or a never-connected one) is impossible to miss. Renders
 * nothing while healthy or still loading, so it never flashes.
 */
export function ConnectionBanner() {
  const token = useAuthToken();
  const { data } = usePolling<WhatsappSessionStatus[]>(
    () => sessions.list({ token }),
    30_000,
    [token],
  );

  if (!data) return null;
  if (data.some((s) => s.status === "WORKING")) return null;

  const hasSession = data.length > 0;

  return (
    <Link
      href="/onboarding/connect"
      className="mb-4 flex items-center gap-3 rounded-2xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm font-semibold text-foreground transition-colors hover:bg-warning/15"
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-warning/20 text-warning-strong">
        <Smartphone className="h-4 w-4" />
      </span>
      <span>
        {hasSession
          ? "Your WhatsApp number looks disconnected — reconnect so the bot keeps replying."
          : "Connect your WhatsApp number to start receiving messages."}
        <span className="ml-1 underline">Open connect →</span>
      </span>
    </Link>
  );
}
