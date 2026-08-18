"use client";

import { useSession } from "next-auth/react";

import { ChangePasswordCard } from "@/components/change-password-card";
import { ThemeToggle } from "@/components/theme-toggle";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";

/**
 * Everything about the person, in one place.
 *
 * The split that organises the whole app: the business and its bot live in the
 * sidebar, the person lives here, reached from the avatar menu. Changing your
 * password used to sit in the middle of the bot's configuration, which is why
 * this page exists.
 */
export default function AccountPage() {
  const { data: session } = useSession();
  const user = session?.user;

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Account</h1>
        <p className="text-sm text-muted-foreground">
          Your profile, password and preferences. These are yours, not your workspace&apos;s.
        </p>
      </div>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Profile</CardTitle>
            <CardDescription>How you appear to your team.</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="account-email">Email</Label>
            <p
              id="account-email"
              className="rounded-xl border border-border bg-surface-muted px-3.5 py-2.5 text-sm"
            >
              {user?.email ?? "Not signed in"}
            </p>
            <p className="text-xs text-muted-foreground">
              Your email is your sign-in and cannot be changed here. Contact support if you need it
              moved.
            </p>
          </div>

          {user?.role ? (
            <div className="space-y-1.5">
              <Label htmlFor="account-role">Role</Label>
              <p
                id="account-role"
                className="rounded-xl border border-border bg-surface-muted px-3.5 py-2.5 text-sm capitalize"
              >
                {String(user.role).replace(/_/g, " ")}
              </p>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <ChangePasswordCard />

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Preferences</CardTitle>
            <CardDescription>How the dashboard looks on this device.</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm">
              <span className="font-semibold">Theme</span>
              <span className="block text-xs text-muted-foreground">
                Follows your system setting until you pick one.
              </span>
            </div>
            <ThemeToggle />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
