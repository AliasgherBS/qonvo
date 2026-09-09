"use client";

import { Bell, Check, Radio, ShieldAlert, TrendingUp, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import type { NotificationType } from "@/lib/api";
import { inboxHref } from "@/lib/api/inbox";
import { notificationsFeed, type FeedNotification } from "@/lib/api/notifications-extras";
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

/**
 * The bell (functional test F6).
 *
 * Two things were wrong with it. The badge could only count up: the mark-read
 * endpoint was called when a row was clicked and at no other time, so an owner
 * who opened the panel, read all three notices and closed it still saw "3", for
 * ever. And there was no way to dismiss one deliberately - clicking a row that
 * linked to a conversation navigated away, which is a different intention.
 *
 * So: opening the panel marks everything read, in one request, and every unread
 * row carries its own control. The rows opened in this session keep their
 * unread styling until the panel is closed, because a highlight that vanishes
 * under the cursor is how you lose your place in a list you are reading.
 *
 * A notice whose basis was later corrected renders as retracted rather than
 * disappearing, and does not count towards the badge. The owner was told the
 * original thing; the honest correction is to say so, not to un-say it.
 */
export function NotificationsBell() {
  const token = useAuthToken();
  const [open, setOpen] = useState(false);
  // Ids that were unread when the panel opened. Styling only.
  const [justRead, setJustRead] = useState<Set<string>>(new Set());
  const marking = useRef(false);

  const { data, refetch } = usePolling<FeedNotification[]>(
    () => notificationsFeed.list({ token }),
    NOTIFICATIONS_POLL_MS,
    [token],
  );

  const items = data ?? [];
  // A retracted notice is not an unread notice. It is a correction of something
  // already delivered, and badging it asks the owner to act on a non-event.
  const unread = items.filter((n) => !n.read && !n.stale);

  async function handleMarkRead(id: string) {
    setJustRead((prev) => new Set(prev).add(id));
    try {
      await notificationsFeed.markRead(id, { token });
      refetch();
    } catch {
      // A failed mark-read is not worth interrupting anybody: the row stays
      // unread and the next poll will show it that way.
    }
  }

  async function handleOpen() {
    setJustRead(new Set(items.filter((n) => !n.read).map((n) => n.id)));
    setOpen(true);
    // Guarded: the panel can be reopened faster than the request completes, and
    // a second call would be a pointless write on an already-clear list.
    if (unread.length === 0 || marking.current) return;
    marking.current = true;
    try {
      await notificationsFeed.markAllRead({ token });
      refetch();
    } catch {
      // Same reasoning as above. The badge stays until the next attempt rather
      // than lying about what was read.
    } finally {
      marking.current = false;
    }
  }

  function close() {
    setOpen(false);
    setJustRead(new Set());
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => (open ? close() : void handleOpen())}
        aria-label={`Notifications${unread.length ? `, ${unread.length} unread` : ""}`}
        className="relative flex h-9 w-9 items-center justify-center rounded-full border border-border text-foreground transition-colors hover:bg-surface-muted"
      >
        <Bell className="h-4 w-4" />
        {unread.length > 0 ? (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-danger-foreground">
            {unread.length > 9 ? "9+" : unread.length}
          </span>
        ) : null}
      </button>

      {open ? (
        <>
          <div className="fixed inset-0 z-40" onClick={close} />
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
                      highlight={!item.read || justRead.has(item.id)}
                      onOpen={() => {
                        close();
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
  highlight,
  onOpen,
  onMarkRead,
}: {
  notification: FeedNotification;
  highlight: boolean;
  onOpen: () => void;
  onMarkRead: () => void;
}) {
  const Icon = iconFor(notification.type);
  const stale = notification.stale;
  const bodyClass = "flex min-w-0 flex-1 items-start gap-3 px-4 py-3 text-left text-sm";

  const contents = (
    <>
      <span
        className={cn(
          "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-muted text-muted-foreground",
          stale && "opacity-50",
        )}
      >
        <Icon className="h-3.5 w-3.5" />
      </span>
      <span className="min-w-0 flex-1">
        {/* The customer, named the way the inbox names them, is the headline: an
            escalation is about a person, and "A customer needs a human" does
            not say which one (teardown S4). */}
        <span
          className={cn(
            "block truncate font-semibold",
            stale && "text-muted-foreground line-through decoration-1",
          )}
        >
          {notification.subject ?? notification.title}
        </span>
        {stale ? (
          // The retraction, in the notice's own row. A correction filed
          // somewhere else is a correction nobody reads.
          <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
            {notification.staleReason}
          </span>
        ) : (
          <span dir="auto" className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
            {/* The trimmed reason, not the whole body: the tail of an escalation
                reason is the model explaining itself to the system. */}
            {[notification.subject ? notification.title : null, notification.summary]
              .filter(Boolean)
              .join(" · ")}
          </span>
        )}
        <span className="mt-0.5 block text-xs text-muted-foreground">
          {formatRelative(notification.createdAt)}
          {stale ? " · No longer applies" : notification.conversationId ? " · Open chat" : ""}
        </span>
      </span>
    </>
  );

  return (
    <div
      className={cn(
        "flex items-start transition-colors hover:bg-surface-muted",
        highlight && !stale && "bg-primary/5",
      )}
    >
      {/* A notification that names a conversation links to it. Opening the chat
          is the only thing an owner wants to do with an escalation, and the bell
          used to be a dead end. */}
      {notification.conversationId ? (
        <Link href={inboxHref(notification.conversationId)} onClick={onOpen} className={bodyClass}>
          {contents}
        </Link>
      ) : (
        <button type="button" onClick={onMarkRead} className={bodyClass}>
          {contents}
        </button>
      )}

      {/* The per-item control. Outside the link on purpose: dismissing a notice
          and opening the conversation it points at are different intentions,
          and one used to be the only way to do the other. */}
      {!notification.read ? (
        <button
          type="button"
          onClick={onMarkRead}
          aria-label="Mark as read"
          title="Mark as read"
          className="group mr-2 mt-3 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-primary transition-colors hover:bg-primary/10"
        >
          <span className="h-2 w-2 rounded-full bg-primary group-hover:hidden" />
          <Check className="hidden h-3.5 w-3.5 group-hover:block" />
        </button>
      ) : null}
    </div>
  );
}
