import type { ConversationState } from "@/lib/api";

export const STATE_LABEL: Record<ConversationState, string> = {
  bot_active: "Bot active",
  paused_by_agent: "Needs human",
  paused_by_owner: "You're replying",
  needs_human: "Needs human",
};

export const STATE_TONE: Record<ConversationState, "success" | "warning" | "danger"> = {
  bot_active: "success",
  paused_by_agent: "warning",
  paused_by_owner: "warning",
  needs_human: "danger",
};

export type FilterTab = "all" | "needs_human" | "paused";

export function matchesTab(state: ConversationState, tab: FilterTab): boolean {
  if (tab === "all") return true;
  if (tab === "needs_human") return state === "needs_human";
  return state === "paused_by_owner" || state === "paused_by_agent";
}

/** First letter of the customer's label, for the avatar (teardown I5). */
export function avatarInitial(displayName: string): string {
  const first = displayName.trim().charAt(0).toUpperCase();
  // A formatted number starts with "+", which is not an initial.
  return /[A-Z\p{L}]/u.test(first) ? first : "";
}
