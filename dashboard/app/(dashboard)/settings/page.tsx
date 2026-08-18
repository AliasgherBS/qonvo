import { redirect } from "next/navigation";

/**
 * Settings used to be a single scroll holding six unrelated concerns plus a
 * password form, so choosing a bot's tone sat beside choosing an LLM model.
 * Those now live on Behavior, Skills, Business and Account.
 *
 * The route is kept as a redirect rather than deleted: it is in muscle memory
 * and in bookmarks, and Behavior is where most of what people came here for
 * ended up.
 */
export default function SettingsPage() {
  redirect("/behavior");
}
