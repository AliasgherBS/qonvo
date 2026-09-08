"use client";

import { Bell, Radio, ShieldAlert, TrendingUp, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import type { NotificationType } from "@/lib/api";
import { inboxHref, inboxNotifications, type InboxNotification } from "@/lib/api/inbox";
import { formatRelative } from "@/lib/format";
import { useAuthToken, usePolling } from "@/lib/use-api";
import { cn } from "@/lib/utils";

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

  const { data, refetch } = usePolling<InboxNotification[]>(
    () => inboxNotifications.list({}, { token }),
    NOTIFICATIONS_POLL_MS,
    [token],
  );

  const items = data ?? [];
  const unreadCount = items.filter((n) => !n.read).length;

  async function handleMarkRead(id: string) {
    try {
      await inboxNotifications.markRead(id, { token });
      refetch();
    } catch {
      // A failed mark-read is not worth interrupting anybody: the row stays
      // unread and the next poll will show it that way.
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
                items.map((item) => (
                  <li key={item.id}>
                    <NotificationRow
                      notification={item}
                      onOpen={() => {
                        setOpen(false);
                        void handleMarkRead(item.id);
                      }}
                      onMarkRead={() => void handleMarkRead(item.id)}
                    />
                  </li>
                ))
              )}
            </ul>
          </div>
        </>
      ) : null}
    </div>
  );
}

function NotificationRow({
  notification,
  onOpen,
  onMarkRead,
}: {
  notification: InboxNotification;
  onOpen: () => void;
  onMarkRead: () => void;
}) {
  const Icon = iconFor(notification.type);
  const rowClass = cn(
    "flex w-full items-start gap-3 px-4 py-3 text-left text-sm transition-colors hover:bg-surface-muted",
    !notification.read && "bg-primary/5",
  );

  const contents = (
    <>
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-muted text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
      </span>
      <span className="min-w-0 flex-1">
        {/* The customer, named the way the inbox names them, is the headline: an
            escalation is about a person, and "A customer needs a human" does
            not say which one (teardown S4). */}
        <span className="block truncate font-semibold">{notification.subject ?? notification.title}</span>
        <span dir="auto" className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
          {/* The trimmed reason, not the whole body: the tail of an escalation
              reason is the model explaining itself to the system. */}
          {[notification.subject ? notification.title : null, notification.summary]
            .filter(Boolean)
            .join(" · ")}
        </span>
        <span className="mt-0.5 block text-xs text-muted-foreground">
          {formatRelative(notification.createdAt)}
          {notification.conversationId ? " · Open chat" : ""}
        </span>
      </span>
      {!notification.read ? <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary" /> : null}
    </>
  );

  // A notification that names a conversation links to it. Opening the chat is
  // the only thing an owner wants to do with an escalation, and the bell used
  // to be a dead end.
  if (notification.conversationId) {
    return (
      <Link href={inboxHref(notification.conversationId)} onClick={onOpen} className={rowClass}>
        {contents}
      </Link>
    );
  }

  return (
    <button type="button" onClick={onMarkRead} className={rowClass}>
      {contents}
    </button>
  );
}
