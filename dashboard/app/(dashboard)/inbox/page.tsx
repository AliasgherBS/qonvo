"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { ConversationList } from "@/components/inbox/conversation-list";
import { matchesTab, type FilterTab } from "@/components/inbox/state";
import { Transcript } from "@/components/inbox/transcript";
import { useFillViewport } from "@/components/inbox/use-fill-viewport";
import { OnboardingChecklist } from "@/components/onboarding-checklist";
import { inbox } from "@/lib/api/inbox";
import { useAuthToken, usePolling } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const TABS: { key: FilterTab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "needs_human", label: "Needs human" },
  { key: "paused", label: "Paused" },
];

const CONVERSATIONS_POLL_MS = 5000;
const SEARCH_DEBOUNCE_MS = 250;

export default function InboxPage() {
  // `useSearchParams` needs a Suspense boundary to prerender, and the boundary
  // has to be above the component that reads it.
  return (
    <Suspense fallback={<div className="h-64 animate-pulse rounded-2xl bg-surface-muted" />}>
      <InboxView />
    </Suspense>
  );
}

function InboxView() {
  const token = useAuthToken();
  const [tab, setTab] = useState<FilterTab>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  // Which pane the phone is showing. Ignored from `lg` up, where both are
  // visible side by side (teardown I3).
  const [mobilePane, setMobilePane] = useState<"list" | "chat">("list");
  const { ref: panesRef, height: panesHeight } = useFillViewport();

  // Searching on every keystroke would fire a request per character against a
  // list that also polls every five seconds.
  useEffect(() => {
    const id = window.setTimeout(() => setSearchTerm(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [search]);

  // Deep link from the notification bell: /inbox?conversation=<id> opens that
  // thread (teardown S4). Read reactively, not once on mount: clicking a
  // notification while already on the inbox is a soft navigation, so the page
  // is never remounted and a mount-only read would ignore it.
  const targetId = useSearchParams().get("conversation");
  useEffect(() => {
    if (targetId) {
      setSelectedId(targetId);
      setMobilePane("chat");
    }
  }, [targetId]);

  const { data, loading, error, refetch } = usePolling(
    () => inbox.list({ q: searchTerm || undefined, limit: 100 }, { token }),
    CONVERSATIONS_POLL_MS,
    [token, searchTerm],
  );

  const items = data?.items ?? null;
  const filtered = useMemo(() => items?.filter((c) => matchesTab(c.state, tab)) ?? null, [items, tab]);
  const selected = useMemo(
    () => items?.find((conversation) => conversation.id === selectedId) ?? null,
    [items, selectedId],
  );
  const unreadCount = data?.unreadConversations ?? 0;

  function handleSelect(id: string) {
    setSelectedId(id);
    setMobilePane("chat");
    // Keeps the address bar honest, so a refresh or a shared link lands on the
    // same thread. replaceState rather than a router push: this is a selection,
    // not a place in the history the back button should walk through. Next
    // patches history, so `useSearchParams` above sees this too and the two
    // cannot drift apart.
    window.history.replaceState(null, "", `/inbox?conversation=${encodeURIComponent(id)}`);
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Inbox</h1>
        <p className="text-sm text-muted-foreground">
          Every conversation your number has, live. Take over any time.
        </p>
      </div>

      {/* Moved here from Settings: it is a first-run aid, not a setting, and
          the inbox is the first place a new owner lands. Compact, because this
          page is a fixed-height workspace and the expanded card is about 450
          pixels of it, which pushed the reply box off the bottom of a 900-pixel
          window for exactly the people who most need the inbox to look
          finished (teardown I2). */}
      <OnboardingChecklist compact />

      <div className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={cn(
              "flex items-center gap-2 rounded-full px-4 py-1.5 text-sm font-semibold transition-colors",
              tab === t.key
                ? "bg-primary text-primary-foreground"
                : "bg-surface-muted text-foreground hover:bg-border",
            )}
          >
            {t.label}
            {/* Only on All, and only when there is something unread: a count of
                zero is noise, and the count is of the whole active set rather
                than of this tab so it does not move when you filter. */}
            {t.key === "all" && unreadCount > 0 ? (
              <span
                className={cn(
                  "flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-[11px] font-bold",
                  tab === t.key ? "bg-primary-foreground text-primary" : "bg-primary text-primary-foreground",
                )}
              >
                {unreadCount > 99 ? "99+" : unreadCount}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      {/*
        A measured pixel height, not `h-full`: the ancestor chain only sets
        min-h-screen, so `h-full` never resolved and the composer ended up below
        the fold (teardown I2). The panes own their own overflow from here down,
        and the page itself no longer scrolls.
      */}
      <div
        ref={panesRef}
        style={panesHeight ? { height: `${panesHeight}px` } : undefined}
        className="grid min-h-0 grid-cols-1 gap-4 overflow-hidden lg:grid-cols-[360px_1fr]"
      >
        <div
          className={cn(
            "flex min-h-0 flex-col overflow-hidden rounded-2xl border border-border bg-surface",
            // One pane at a time on a phone. Both panes used to render stacked,
            // so tapping a row drew the transcript below the whole list, off
            // screen, and looked like nothing had happened (teardown I3).
            mobilePane === "chat" && "hidden lg:flex",
          )}
        >
          <ConversationList
            conversations={filtered}
            loading={loading}
            error={error}
            selectedId={selectedId}
            search={search}
            onSearchChange={setSearch}
            onSelect={handleSelect}
            onRetry={refetch}
          />
        </div>

        <div
          className={cn(
            "min-h-0 overflow-hidden rounded-2xl border border-border bg-surface",
            mobilePane === "list" && "hidden lg:block",
          )}
        >
          <Transcript
            key={selected?.id ?? "none"}
            conversation={selected}
            onChanged={refetch}
            onBack={() => setMobilePane("list")}
          />
        </div>
      </div>
    </div>
  );
}
