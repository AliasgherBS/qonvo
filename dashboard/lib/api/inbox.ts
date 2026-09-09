/**
 * Inbox and notification endpoints (teardown I1, I4, S4).
 *
 * Lives here rather than in `lib/api.ts` because that file is the one every
 * feature collides in; `apiFetch` is exported precisely so a domain can own its
 * own client module. The existing `conversations` group in `lib/api.ts` still
 * owns messages/takeover/release/reply -- only the list, which grew a search
 * term and a display name, and the notification list, which grew a link
 * through to the conversation, are re-declared here.
 */

import { apiFetch, type CallOpts, type ConversationState, type NotificationType } from "@/lib/api";

function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

interface InboxConversationDto {
  id: string;
  chat_id: string;
  customer_name: string | null;
  display_name: string;
  state: ConversationState;
  last_message_preview: string | null;
  last_activity_at: string;
  unread: number;
}

export interface InboxConversation {
  id: string;
  /** The raw WhatsApp address. Shown only as a tooltip / secondary line. */
  chatId: string;
  /** The WhatsApp push name, when one has ever arrived for this chat. */
  customerName: string | null;
  /**
   * What to render as the conversation title: the push name, a formatted
   * number, or a short label for a Linked ID. Computed by the backend so the
   * inbox and the notification bell cannot disagree about a customer's name.
   */
  displayName: string;
  state: ConversationState;
  lastMessagePreview: string | null;
  lastActivityAt: string;
  /** Unread inbound messages. Cleared when the transcript is opened. */
  unread: number;
}

export interface InboxListResult {
  items: InboxConversation[];
  total: number;
  /** Conversations with anything unread, across the whole active set. */
  unreadConversations: number;
}

interface InboxListDto {
  items: InboxConversationDto[];
  total: number;
  unread_conversations: number;
}

function mapConversation(dto: InboxConversationDto): InboxConversation {
  return {
    id: dto.id,
    chatId: dto.chat_id,
    customerName: dto.customer_name,
    displayName: dto.display_name,
    state: dto.state,
    lastMessagePreview: dto.last_message_preview,
    lastActivityAt: dto.last_activity_at,
    unread: dto.unread,
  };
}

export const inbox = {
  list: (
    params: { state?: ConversationState; q?: string; limit?: number; offset?: number } = {},
    opts: CallOpts = {},
  ) =>
    apiFetch<InboxListDto>(`/api/conversations${query(params)}`, opts).then(
      (dto): InboxListResult => ({
        items: dto.items.map(mapConversation),
        total: dto.total,
        unreadConversations: dto.unread_conversations,
      }),
    ),
};

interface InboxNotificationDto {
  id: string;
  type: NotificationType;
  title: string;
  body: string | null;
  summary: string | null;
  read: boolean;
  conversation_id: string | null;
  subject: string | null;
  created_at: string;
}

export interface InboxNotification {
  id: string;
  type: NotificationType;
  title: string;
  /** The full body. Kept so nothing is hidden from the owner. */
  body: string | null;
  /**
   * The body's first sentence. An escalation body is the model's own `reason`,
   * which ends by explaining itself to the system; that is what the bell used
   * to quote at the owner (teardown S4).
   */
  summary: string | null;
  read: boolean;
  /** The conversation this is about, when it names one, so the row can link. */
  conversationId: string | null;
  /** That conversation's customer, named the same way the inbox names them. */
  subject: string | null;
  createdAt: string;
}

function mapNotification(dto: InboxNotificationDto): InboxNotification {
  return {
    id: dto.id,
    type: dto.type,
    title: dto.title,
    body: dto.body,
    summary: dto.summary,
    read: dto.read,
    conversationId: dto.conversation_id,
    subject: dto.subject,
    createdAt: dto.created_at,
  };
}

export const inboxNotifications = {
  list: (params: { unread?: boolean } = {}, opts: CallOpts = {}) =>
    apiFetch<InboxNotificationDto[]>(`/api/notifications${query(params)}`, opts).then((items) =>
      items.map(mapNotification),
    ),

  markRead: (id: string, opts: CallOpts = {}) =>
    apiFetch<void>(`/api/notifications/${id}/read`, { method: "POST", ...opts }),
};

/** Deep link to one conversation in the inbox (the bell's link-through). */
export function inboxHref(conversationId: string): string {
  return `/inbox?conversation=${encodeURIComponent(conversationId)}`;
}
