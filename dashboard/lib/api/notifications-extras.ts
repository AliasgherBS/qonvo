/**
 * The two things the notification bell needed and the existing client did not
 * carry (functional test F6).
 *
 * 1. `markAllRead`. The per-item endpoint existed and was only ever called when
 *    a row was clicked, so the badge counted up and never down: an owner who
 *    read every notification still saw "3". Opening the panel is the moment
 *    they were read, and one request is what that should cost.
 * 2. `stale` / `staleReason`. A notice whose basis was later corrected is kept
 *    and shown with its retraction attached rather than deleted, so the reader
 *    can see both what they were told and that it no longer holds.
 *
 * Its own module rather than an edit to `lib/api/inbox.ts` or `lib/api.ts`, for
 * the reason `inbox.ts` gives itself: `apiFetch` is exported precisely so a
 * domain can own its client code instead of everything colliding in one file.
 */

import { apiFetch, type CallOpts, type NotificationType } from "@/lib/api";
import type { InboxNotification } from "@/lib/api/inbox";

interface NotificationDto {
  id: string;
  type: NotificationType;
  title: string;
  body: string | null;
  summary: string | null;
  read: boolean;
  stale: boolean;
  stale_reason: string | null;
  conversation_id: string | null;
  subject: string | null;
  created_at: string;
}

export interface FeedNotification extends InboxNotification {
  /** True when the thing this notice claims is no longer the case. */
  stale: boolean;
  /** Why, in words meant for the owner. Null unless `stale`. */
  staleReason: string | null;
}

function map(dto: NotificationDto): FeedNotification {
  return {
    id: dto.id,
    type: dto.type,
    title: dto.title,
    body: dto.body,
    summary: dto.summary,
    read: dto.read,
    stale: dto.stale,
    staleReason: dto.stale_reason,
    conversationId: dto.conversation_id,
    subject: dto.subject,
    createdAt: dto.created_at,
  };
}

export const notificationsFeed = {
  /** Every notification for this tenant, newest first, retractions included. */
  list: (opts: CallOpts = {}) =>
    apiFetch<NotificationDto[]>("/api/notifications", opts).then((rows) => rows.map(map)),

  markRead: (id: string, opts: CallOpts = {}) =>
    apiFetch<void>(`/api/notifications/${id}/read`, { method: "POST", ...opts }),

  /** Clear the badge in one call. Returns how many rows changed. */
  markAllRead: (opts: CallOpts = {}) =>
    apiFetch<{ marked: number }>("/api/notifications/read-all", { method: "POST", ...opts }),
};
