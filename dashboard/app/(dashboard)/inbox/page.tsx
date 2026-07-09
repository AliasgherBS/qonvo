"use client";

import { Inbox as InboxIcon, MessageCircle, Pause, Play, UserRound } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { conversations, type Conversation, type ConversationState } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

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

export default function InboxPage() {
  const { data, loading, error, refetch } = useApi(() => conversations.list());
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selected = useMemo(
    () => data?.find((conversation) => conversation.id === selectedId) ?? null,
    [data, selectedId],
  );

  return (
    <div className="flex h-full flex-col gap-4">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Inbox</h1>
        <p className="text-sm text-muted-foreground">
          Every conversation your number has, live — take over any time.
        </p>
      </div>

      <div className="grid flex-1 grid-cols-1 gap-4 overflow-hidden lg:grid-cols-[360px_1fr]">
        <div className="flex flex-col overflow-hidden rounded-2xl border border-border bg-surface">
          <ConversationList
            conversations={data}
            loading={loading}
            error={error}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onRetry={refetch}
          />
        </div>

        <div className="overflow-hidden rounded-2xl border border-border bg-surface">
          <Transcript conversation={selected} onChanged={refetch} />
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
  if (loading) {
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

  if (error) {
    return (
      <div className="p-4">
        <EmptyState
          icon={<InboxIcon className="h-5 w-5" />}
          title="Can't reach the backend yet"
          description="The inbox will populate once the Qonvo API is connected."
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
              <span className="truncate text-sm font-semibold">
                {conversation.customerName ?? conversation.customerNumber}
              </span>
              <Badge tone={STATE_TONE[conversation.state]}>{STATE_LABEL[conversation.state]}</Badge>
            </div>
            <p className="truncate text-sm text-muted-foreground">
              {conversation.lastMessagePreview ?? "No messages yet"}
            </p>
          </button>
        </li>
      ))}
    </ul>
  );
}

function Transcript({
  conversation,
  onChanged,
}: {
  conversation: Conversation | null;
  onChanged: () => void;
}) {
  const [pending, setPending] = useState(false);

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
  const conversationId = conversation.id;

  async function handleTakeover() {
    setPending(true);
    try {
      await conversations.takeover(conversationId);
      onChanged();
    } catch {
      // Backend not wired yet in Phase 0 — action is inert until it lands.
    } finally {
      setPending(false);
    }
  }

  async function handleRelease() {
    setPending(true);
    try {
      await conversations.release(conversationId);
      onChanged();
    } catch {
      // Backend not wired yet in Phase 0 — action is inert until it lands.
    } finally {
      setPending(false);
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
            <p className="text-sm font-bold">{conversation.customerName ?? conversation.customerNumber}</p>
            <p className="text-xs text-muted-foreground">{conversation.customerNumber}</p>
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
        <EmptyState
          icon={<MessageCircle className="h-5 w-5" />}
          title="Transcript will appear here"
          description="Messages, media, and voice notes for this conversation load once the messaging API is live."
        />
      </div>
    </div>
  );
}
