"use client";

import { Inbox as InboxIcon, Search, UserRound, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { avatarInitial, STATE_LABEL, STATE_TONE } from "@/components/inbox/state";
import type { InboxConversation } from "@/lib/api/inbox";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

export function ConversationList({
  conversations: items,
  loading,
  error,
  selectedId,
  search,
  onSearchChange,
  onSelect,
  onRetry,
}: {
  conversations: InboxConversation[] | null;
  loading: boolean;
  error: string | null;
  selectedId: string | null;
  search: string;
  onSearchChange: (value: string) => void;
  onSelect: (id: string) => void;
  onRetry: () => void;
}) {
  return (
    <>
      {/* Outside the scroll area: at three hundred conversations the search
          field is the only way in, and a field that scrolls away is not one
          (teardown I4). */}
      <div className="shrink-0 border-b border-border p-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search name or number"
            aria-label="Search conversations"
            className="pl-9 pr-9"
          />
          {search ? (
            <button
              type="button"
              onClick={() => onSearchChange("")}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground hover:bg-border"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          ) : null}
        </div>
      </div>

      <ListBody
        conversations={items}
        loading={loading}
        error={error}
        search={search}
        selectedId={selectedId}
        onSelect={onSelect}
        onRetry={onRetry}
      />
    </>
  );
}

function ListBody({
  conversations: items,
  loading,
  error,
  search,
  selectedId,
  onSelect,
  onRetry,
}: {
  conversations: InboxConversation[] | null;
  loading: boolean;
  error: string | null;
  search: string;
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
        {search ? (
          <EmptyState
            icon={<Search className="h-5 w-5" />}
            title="No matches"
            description={`Nothing here matches "${search}". Names come from WhatsApp, so a customer who has none is searchable by number.`}
          />
        ) : (
          <EmptyState
            icon={<InboxIcon className="h-5 w-5" />}
            title="No conversations yet"
            description="The moment a customer messages your WhatsApp number, it shows up here."
          />
        )}
      </div>
    );
  }

  return (
    <ul className="scrollbar-thin min-h-0 flex-1 divide-y divide-border overflow-y-auto">
      {items.map((conversation) => (
        <li key={conversation.id}>
          <ConversationRow
            conversation={conversation}
            selected={selectedId === conversation.id}
            onSelect={onSelect}
          />
        </li>
      ))}
    </ul>
  );
}

function ConversationRow({
  conversation,
  selected,
  onSelect,
}: {
  conversation: InboxConversation;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const initial = avatarInitial(conversation.displayName);
  return (
    <button
      type="button"
      onClick={() => onSelect(conversation.id)}
      // The raw WhatsApp address is still available, as a tooltip rather than
      // as the title it used to be (teardown I1).
      title={conversation.chatId}
      className={cn(
        "flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-muted",
        selected && "bg-primary/10",
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-bold",
          conversation.unread > 0
            ? "bg-primary text-primary-foreground"
            : "bg-surface-muted text-muted-foreground",
        )}
        aria-hidden
      >
        {initial || <UserRound className="h-4 w-4" />}
      </span>

      <span className="min-w-0 flex-1">
        <span className="flex items-center justify-between gap-2">
          <span
            className={cn(
              "truncate text-sm",
              conversation.unread > 0 ? "font-extrabold" : "font-semibold",
            )}
          >
            {conversation.displayName}
          </span>
          <span className="shrink-0 text-xs text-muted-foreground">
            {formatRelative(conversation.lastActivityAt)}
          </span>
        </span>
        <span className="mt-1 flex items-center justify-between gap-2">
          {/* dir="auto" so an Urdu preview truncates from its own end instead of
              putting the ellipsis at the start of the sentence (teardown I5). */}
          <span
            dir="auto"
            className={cn(
              "truncate text-sm leading-relaxed",
              conversation.unread > 0 ? "text-foreground" : "text-muted-foreground",
            )}
          >
            {conversation.lastMessagePreview ?? "No messages yet"}
          </span>
          {conversation.unread > 0 ? (
            <span className="flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-primary px-1.5 text-[11px] font-bold text-primary-foreground">
              {conversation.unread > 9 ? "9+" : conversation.unread}
            </span>
          ) : null}
        </span>
        <span className="mt-1.5 flex">
          <Badge tone={STATE_TONE[conversation.state]}>{STATE_LABEL[conversation.state]}</Badge>
        </span>
      </span>
    </button>
  );
}
