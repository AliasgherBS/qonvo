"use client";

import { Bell, Radio, ShieldAlert, TrendingUp, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { notifications, type Notification, type NotificationType } from "@/lib/api";
import { useAuthToken, usePolling } from "@/lib/use-api";
import { cn, formatRelativeTime } from "@/lib/utils";

const NOTIFICATIONS_POLL_MS = 30_000;

// Keyed by the real backend enum. A partial record + fallback means a new/unknown
// type (e.g. a future notification kind) renders a default icon instead of
// crashing the whole bell with `<undefined />`.
const TYPE_ICON: Partial<Record<NotificationType, typeof Bell>> = {
  escalation: ShieldAlert,
  disconnect: Radio,
  quota_warning: TriangleAlert,
  session_failed: TriangleAlert,
};

function iconFor(type: NotificationType): typeof Bell {
  return TYPE_ICON[type] ?? TrendingUp;
}

export function NotificationsBell() {
  const token = useAuthToken();
  const [open, setOpen] = useState(false);

  const { data, refetch } = usePolling<Notification[]>(
    () => notifications.list({}, { token }),
    NOTIFICATIONS_POLL_MS,
    [token],
  );

  const items = data ?? [];
  const unreadCount = items.filter((n) => !n.read).length;

  async function handleMarkRead(id: string) {
    try {
      await notifications.markRead(id, { token });
      refetch();
    } catch {
      // Backend not wired yet — the bell stays inert until it lands.
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={`Notifications${unreadCount ? `, ${unreadCount} unread` : ""}`}
        className="relative flex h-9 w-9 items-center justify-center rounded-full border border-border text-foreground transition-colors hover:bg-surface-muted"
      >
        <Bell className="h-4 w-4" />
        {unreadCount > 0 ? (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-danger-foreground">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        ) : null}
      </button>

      {open ? (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-50 mt-2 w-80 overflow-hidden rounded-2xl border border-border bg-surface shadow-xl">
            <div className="border-b border-border px-4 py-3">
              <p className="text-sm font-bold">Notifications</p>
            </div>
            <ul className="max-h-96 divide-y divide-border overflow-y-auto">
              {items.length === 0 ? (
                <li className="px-4 py-6 text-center text-sm text-muted-foreground">You&apos;re all caught up.</li>
              ) : (
                items.map((item) => {
                  const Icon = iconFor(item.type);
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        onClick={() => handleMarkRead(item.id)}
                        className={cn(
                          "flex w-full items-start gap-3 px-4 py-3 text-left text-sm transition-colors hover:bg-surface-muted",
                          !item.read && "bg-primary/5",
                        )}
                      >
                        <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-muted text-muted-foreground">
                          <Icon className="h-3.5 w-3.5" />
                        </span>
                        <span className="flex-1">
                          <span className="block">{item.message}</span>
                          <span className="mt-0.5 block text-xs text-muted-foreground">
                            {formatRelativeTime(item.createdAt)}
                          </span>
                        </span>
                        {!item.read ? <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary" /> : null}
                      </button>
                    </li>
                  );
                })
              )}
            </ul>
          </div>
        </>
      ) : null}
    </div>
  );
}
