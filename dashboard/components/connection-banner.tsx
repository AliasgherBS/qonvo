"use client";

import { Smartphone } from "lucide-react";
import Link from "next/link";

import { sessions, type Role, type WhatsappSessionStatus } from "@/lib/api";
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
 */
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
  const shell =
    "mb-4 flex items-center gap-3 rounded-2xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm font-semibold text-foreground";

  const icon = (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-warning/20 text-warning-strong">
      <Smartphone className="h-4 w-4" />
    </span>
  );

  if (role !== "owner") {
    return (
      <div className={shell}>
        {icon}
        <span>
          {hasSession
            ? "The WhatsApp number looks disconnected, so the rep is not replying. Ask the owner to reconnect it."
            : "No WhatsApp number is connected yet, so the rep is not replying. The owner can connect one."}
        </span>
      </div>
    );
  }

  return (
    <Link href="/onboarding/connect" className={`${shell} transition-colors hover:bg-warning/15`}>
      {icon}
      <span>
        {hasSession
          ? "Your WhatsApp number looks disconnected. Reconnect so the bot keeps replying."
          : "Connect your WhatsApp number to start receiving messages."}
        <span className="ml-1 underline">Open connect →</span>
      </span>
    </Link>
  );
}
