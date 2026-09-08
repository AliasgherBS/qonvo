"use client";

import { ProfileCard } from "@/components/account/profile-card";
import { SessionsCard } from "@/components/account/sessions-card";
import { TwoFactorCard } from "@/components/account/two-factor-card";
import { ChangePasswordCard } from "@/components/change-password-card";

/**
 * Everything about the person, in one place (teardown V5, V6, V7).
 *
 * The split that organises the whole app: the business and its bot live in the
 * sidebar, the person lives here, reached from the avatar menu. Changing your
 * password used to sit in the middle of the bot's configuration, which is why
 * this page exists.
 *
 * As shipped it was close to empty and missing what anybody expects to find in
 * an account: no name to edit, no two-factor, no way to sign out everywhere.
 * All three are here now.
 *
 * The theme control is deliberately **not** here. It appeared twice, once under
 * a Preferences card on this page and once in the avatar menu, and two controls
 * for one setting is how they drift apart. The menu is the one that survives:
 * it is one click from every page in the product, and it is the menu that opens
 * this page, so it is directly above wherever somebody looked for it.
 *
 * The workspace's data export stays on Team for now. It is an account-level
 * concern wearing a page action's costume and the teardown is right that it
 * belongs here, but it is one owner-only tenant export rather than a personal
 * one, and moving it means editing Team.
 */
export default function AccountPage() {
  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Account</h1>
        <p className="text-sm text-muted-foreground">
          Your name, your password and your sign-in security. These are yours, not your
          workspace&apos;s.
        </p>
      </div>

      <ProfileCard />
      <ChangePasswordCard />
      <TwoFactorCard />
      <SessionsCard />
    </div>
  );
}
