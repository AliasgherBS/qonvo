"use client";

import { Inbox as InboxIcon, MessageCircle, Pause, Play, Send, UserRound } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { conversations, describeError, type Conversation, type ConversationState, type Message } from "@/lib/api";
import { useAuthToken, usePolling } from "@/lib/use-api";
import { cn, formatRelativeTime } from "@/lib/utils";

const STATE_LABEL: Record<ConversationState, string> = {
  bot_active: "Bot active",
  paused_by_agent: "Needs human",
  paused_by_owner: "You're replying",
  needs_human: "Needs human",
};

const STATE_TONE: Record<ConversationState, "success" | "warning" | "danger"> = {
  bot_active: "success",
  paused_by_agent: "warning",
  paused_by_owner: "warning",
  needs_human: "danger",
};

type FilterTab = "all" | "needs_human" | "paused";

const TABS: { key: FilterTab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "needs_human", label: "Needs human" },
  { key: "paused", label: "Paused" },
];

const CONVERSATIONS_POLL_MS = 5000;
const MESSAGES_POLL_MS = 5000;

function matchesTab(state: ConversationState, tab: FilterTab): boolean {
  if (tab === "all") return true;
  if (tab === "needs_human") return state === "needs_human";
  return state === "paused_by_owner" || state === "paused_by_agent";
}

export default function InboxPage() {
  const token = useAuthToken();
  const [tab, setTab] = useState<FilterTab>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data, loading, error, refetch } = usePolling(
    () => conversations.list({ limit: 100 }, { token }),
    CONVERSATIONS_POLL_MS,
    [token],
  );

  const items = data?.items ?? null;
  const filtered = useMemo(() => items?.filter((c) => matchesTab(c.state, tab)) ?? null, [items, tab]);
  const selected = useMemo(
    () => items?.find((conversation) => conversation.id === selectedId) ?? null,
    [items, selectedId],
  );

  return (
    <div className="flex h-full flex-col gap-4">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Inbox</h1>
        <p className="text-sm text-muted-foreground">
          Every conversation your number has, live — take over any time.
        </p>
      </div>

      <div className="flex gap-2">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={cn(
              "rounded-full px-4 py-1.5 text-sm font-semibold transition-colors",
              tab === t.key
                ? "bg-primary text-primary-foreground"
                : "bg-surface-muted text-foreground hover:bg-border",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="grid flex-1 grid-cols-1 gap-4 overflow-hidden lg:grid-cols-[360px_1fr]">
        <div className="flex flex-col overflow-hidden rounded-2xl border border-border bg-surface">
          <ConversationList
            conversations={filtered}
            loading={loading}
            error={error}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onRetry={refetch}
          />
        </div>

        <div className="overflow-hidden rounded-2xl border border-border bg-surface">
          <Transcript key={selected?.id ?? "none"} conversation={selected} onChanged={refetch} />
        </div>
      </div>
    </div>
  );
}

function ConversationList({
  conversations: items,
  loading,
  error,
  selectedId,
  onSelect,
  onRetry,
}: {
  conversations: Conversation[] | null;
  loading: boolean;
  error: string | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onRetry: () => void;
}) {
  if (loading && !items) {
    return (
      <div className="space-y-3 p-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-3">
            <Skeleton className="h-10 w-10 rounded-full" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-3 w-2/3" />
              <Skeleton className="h-3 w-1/3" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (error && !items) {
    return (
      <div className="p-4">
        <EmptyState
          icon={<InboxIcon className="h-5 w-5" />}
          title="Couldn't load"
          description={error}
          action={
            <Button variant="outline" size="sm" onClick={onRetry}>
              Retry
            </Button>
          }
        />
      </div>
    );
  }

  if (!items || items.length === 0) {
    return (
      <div className="p-4">
        <EmptyState
          icon={<InboxIcon className="h-5 w-5" />}
          title="No conversations yet"
          description="The moment a customer messages your WhatsApp number, it shows up here."
        />
      </div>
    );
  }

  return (
    <ul className="scrollbar-thin flex-1 overflow-y-auto divide-y divide-border">
      {items.map((conversation) => (
        <li key={conversation.id}>
          <button
            type="button"
            onClick={() => onSelect(conversation.id)}
            className={cn(
              "flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors hover:bg-surface-muted",
              selectedId === conversation.id && "bg-primary/10",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-2">
                {conversation.unread ? (
                  <span className="h-2 w-2 shrink-0 rounded-full bg-primary" aria-hidden />
                ) : null}
                <span className="truncate text-sm font-semibold">{conversation.chatId}</span>
              </span>
              <Badge tone={STATE_TONE[conversation.state]}>{STATE_LABEL[conversation.state]}</Badge>
            </div>
            <div className="flex items-center justify-between gap-2">
              <p className="truncate text-sm text-muted-foreground">
                {conversation.lastMessagePreview ?? "No messages yet"}
              </p>
              <span className="shrink-0 text-xs text-muted-foreground">
                {formatRelativeTime(conversation.lastActivityAt)}
              </span>
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

const AUTHOR_LABEL: Record<Message["author"], string> = {
  bot: "Bot",
  human: "You",
  customer: "Customer",
};

function MessageBubble({ message }: { message: Message }) {
  const isOutbound = message.direction === "outbound";
  return (
    <div className={cn("flex flex-col gap-1", isOutbound ? "items-end" : "items-start")}>
      <span className="text-xs font-semibold text-muted-foreground">{AUTHOR_LABEL[message.author]}</span>
      <div
        className={cn(
          "max-w-[75%] rounded-2xl px-4 py-2.5 text-sm",
          isOutbound
            ? message.author === "human"
              ? "bg-primary text-primary-foreground"
              : "bg-primary/15 text-primary-strong"
            : "bg-surface-muted text-foreground",
        )}
      >
        {message.body}
      </div>
      <span className="text-xs text-muted-foreground">{formatRelativeTime(message.createdAt)}</span>
    </div>
  );
}

function Transcript({
  conversation,
  onChanged,
}: {
  conversation: Conversation | null;
  onChanged: () => void;
}) {
  const token = useAuthToken();
  const [pending, setPending] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);

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
  const conversationId2 = conversation.id;
  const allMessages = [...(messagesData?.items ?? []), ...optimisticMessages].sort(
    (a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime(),
  );

  async function handleTakeover() {
    setPending(true);
    try {
      await conversations.takeover(conversationId2, { token });
      onChanged();
    } catch {
      // Backend not wired yet — action is inert until it lands.
    } finally {
      setPending(false);
    }
  }

  async function handleRelease() {
    setPending(true);
    try {
      await conversations.release(conversationId2, { token });
      onChanged();
    } catch {
      // Backend not wired yet — action is inert until it lands.
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
      await conversations.reply(conversationId2, text, { token });
      refetchMessages();
    } catch (err) {
      setSendError(describeError(err, "Couldn't send your reply. Please try again."));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-surface-muted">
            <UserRound className="h-4 w-4" />
          </div>
          <div>
            <p className="text-sm font-bold">{conversation.chatId}</p>
            <p className="text-xs text-muted-foreground">{STATE_LABEL[conversation.state]}</p>
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

      <div className="flex-1 overflow-y-auto p-6">
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
          <div className="space-y-4">
            {allMessages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
          </div>
        )}
      </div>

      <form onSubmit={handleSend} className="border-t border-border p-4">
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
