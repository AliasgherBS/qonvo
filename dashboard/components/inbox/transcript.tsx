"use client";

import { ArrowLeft, MessageCircle, Pause, Play, Send, UserRound } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { avatarInitial, STATE_LABEL } from "@/components/inbox/state";
import { conversations, describeError, type Message } from "@/lib/api";
import type { InboxConversation } from "@/lib/api/inbox";
import { formatDate, formatTime } from "@/lib/format";
import { useAuthToken, usePolling } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const MESSAGES_POLL_MS = 5000;

export function Transcript({
  conversation,
  onChanged,
  onBack,
}: {
  conversation: InboxConversation | null;
  onChanged: () => void;
  /** Mobile only: return to the list, which is the pane it replaced (I3). */
  onBack: () => void;
}) {
  const token = useAuthToken();
  const [pending, setPending] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const conversationId = conversation?.id ?? null;

  const {
    data: messagesData,
    loading: messagesLoading,
    error: messagesError,
    refetch: refetchMessages,
  } = usePolling(
    () =>
      conversationId
        ? conversations.messages(conversationId, { limit: 50 }, { token })
        : Promise.resolve({ items: [] }),
    MESSAGES_POLL_MS,
    [conversationId, token],
  );

  // Once the poll picks up a real outbound message with the same body, drop
  // the optimistic stand-in so it isn't shown twice.
  useEffect(() => {
    if (!messagesData) return;
    setOptimisticMessages((prev) =>
      prev.filter(
        (local) => !messagesData.items.some((real) => real.direction === "outbound" && real.body === local.body),
      ),
    );
  }, [messagesData]);

  const allMessages = useMemo(
    () =>
      [...(messagesData?.items ?? []), ...optimisticMessages].sort(
        (a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime(),
      ),
    [messagesData, optimisticMessages],
  );

  // A transcript that opens at the top shows the oldest message, which is the
  // one nobody is looking for.
  const lastMessageId = allMessages[allMessages.length - 1]?.id;
  useEffect(() => {
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [lastMessageId]);

  if (!conversation) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <EmptyState
          icon={<MessageCircle className="h-5 w-5" />}
          title="Select a conversation"
          description="Pick a conversation on the left to read the transcript and take over if needed."
        />
      </div>
    );
  }

  const isPaused = conversation.state !== "bot_active";
  const isTakenOver = conversation.state === "paused_by_owner";
  const selectedId = conversation.id;
  const initial = avatarInitial(conversation.displayName);

  async function handleTakeover() {
    setPending(true);
    try {
      await conversations.takeover(selectedId, { token });
      onChanged();
    } catch (err) {
      setSendError(describeError(err, "Couldn't take over this conversation."));
    } finally {
      setPending(false);
    }
  }

  async function handleRelease() {
    setPending(true);
    try {
      await conversations.release(selectedId, { token });
      onChanged();
    } catch (err) {
      setSendError(describeError(err, "Couldn't hand this back to the bot."));
    } finally {
      setPending(false);
    }
  }

  async function handleSend(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;

    setDraft("");
    setSendError(null);
    setOptimisticMessages((prev) => [
      ...prev,
      {
        id: `pending-${Date.now()}`,
        direction: "outbound",
        author: "human",
        type: "text",
        body: text,
        createdAt: new Date().toISOString(),
      },
    ]);

    setSending(true);
    try {
      await conversations.reply(selectedId, text, { token });
      refetchMessages();
    } catch (err) {
      setSendError(describeError(err, "Couldn't send your reply. Please try again."));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-4 py-3 lg:px-5 lg:py-4">
        <div className="flex min-w-0 items-center gap-2 lg:gap-3">
          <button
            type="button"
            onClick={onBack}
            aria-label="Back to conversations"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-foreground transition-colors hover:bg-surface-muted lg:hidden"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface-muted text-sm font-bold text-muted-foreground">
            {initial || <UserRound className="h-4 w-4" />}
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-bold" title={conversation.chatId}>
              {conversation.displayName}
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {/* The state, and the raw address when the name is a push name, so
                  nothing the owner used to see is gone (teardown I1). */}
              {conversation.customerName
                ? `${STATE_LABEL[conversation.state]} · ${conversation.chatId}`
                : STATE_LABEL[conversation.state]}
            </p>
          </div>
        </div>

        {isPaused ? (
          <Button size="sm" variant="secondary" onClick={handleRelease} disabled={pending}>
            <Play className="h-4 w-4" />
            Resume bot
          </Button>
        ) : (
          <Button size="sm" variant="outline" onClick={handleTakeover} disabled={pending}>
            <Pause className="h-4 w-4" />
            Take over
          </Button>
        )}
      </div>

      <div ref={scrollRef} className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-4 lg:p-6">
        {messagesLoading && allMessages.length === 0 ? (
          <div className="space-y-4">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className={cn("h-12 w-2/3 rounded-2xl", i % 2 ? "ml-auto" : "")} />
            ))}
          </div>
        ) : messagesError && allMessages.length === 0 ? (
          <EmptyState
            icon={<MessageCircle className="h-5 w-5" />}
            title="Couldn't load this transcript"
            description={messagesError}
          />
        ) : allMessages.length === 0 ? (
          <EmptyState
            icon={<MessageCircle className="h-5 w-5" />}
            title="No messages yet"
            description="Once this customer writes in, their messages show up here."
          />
        ) : (
          <div className="space-y-3">
            {withDaySeparators(allMessages).map((entry) =>
              entry.kind === "day" ? (
                <DaySeparator key={`day-${entry.key}`} label={entry.label} />
              ) : (
                <MessageBubble key={entry.message.id} message={entry.message} />
              ),
            )}
          </div>
        )}
      </div>

      <form onSubmit={handleSend} className="shrink-0 border-t border-border p-4">
        {sendError ? <p className="mb-2 text-xs text-danger">{sendError}</p> : null}
        <div className="flex items-center gap-2">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={isTakenOver ? "Reply as your business…" : "Take over to reply as your business"}
            disabled={!isTakenOver || sending}
          />
          <Button type="submit" size="md" disabled={!isTakenOver || sending || !draft.trim()}>
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </form>
    </div>
  );
}

type TranscriptEntry =
  | { kind: "day"; key: string; label: string }
  | { kind: "message"; message: Message };

/**
 * Insert a separator whenever the calendar day changes.
 *
 * Without one, every message in a week-old thread reads "2 days ago" and the
 * transcript has no timeline at all (teardown I4).
 */
export function withDaySeparators(messages: Message[]): TranscriptEntry[] {
  const entries: TranscriptEntry[] = [];
  let currentDay: string | null = null;
  for (const message of messages) {
    const day = dayKey(message.createdAt);
    if (day !== currentDay) {
      currentDay = day;
      entries.push({ kind: "day", key: day, label: dayLabel(message.createdAt) });
    }
    entries.push({ kind: "message", message });
  }
  return entries;
}

/** A stable per-day key. Never rendered, so its shape does not matter. */
function dayKey(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "unknown" : date.toDateString();
}

function dayLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return "Today";
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  // Everything older goes through the one date helper in the product, so a day
  // never reads as an ambiguous 9/5/2026 (teardown K4).
  return formatDate(date);
}

function DaySeparator({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 py-1">
      <span className="h-px flex-1 bg-border" />
      <span className="text-xs font-semibold text-muted-foreground">{label}</span>
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isOutbound = message.direction === "outbound";
  return (
    <div className={cn("flex flex-col gap-1", isOutbound ? "items-end" : "items-start")}>
      {/* No "Customer"/"Bot" label above the bubble: side and colour already say
          it, and the label was on every single message (teardown I5). Which of
          the two outbound authors sent it is the one thing colour alone does
          not settle, so that lives in the meta line below. */}
      <div
        dir="auto"
        className={cn(
          "max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed lg:max-w-[75%]",
          isOutbound
            ? message.author === "human"
              ? "bg-primary text-primary-foreground"
              : "bg-primary/15 text-primary-strong"
            : "bg-surface-muted text-foreground",
        )}
      >
        {message.body}
      </div>
      <span className="text-xs text-muted-foreground">
        {message.author === "bot" ? "Bot · " : ""}
        {formatTime(message.createdAt)}
      </span>
    </div>
  );
}
