"use client";

import { signOut } from "next-auth/react";
import type { ReactNode } from "react";

import { auth } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAuthToken } from "@/lib/use-api";

/**
 * `className` overrides the default icon-button shape, which is what the
 * account menu needs: there it is a full-width row, not a round icon.
 */
export function SignOutButton({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const token = useAuthToken();

  /**
   * Revoke the credential, then drop the cookie (teardown X6).
   *
   * In that order, and the revoke is awaited: `signOut` navigates away, and a
   * request started but not awaited is cancelled by the navigation. Which
   * would leave exactly the bug being fixed -- a browser that looks signed out
   * holding a token that still works.
   *
   * A failed revoke still signs out locally. Refusing to sign somebody out
   * because the server did not answer is worse than a token that expires on
   * its own within the day.
   */
  async function handleSignOut() {
    try {
      if (token) await auth.logout({ token });
    } catch {
      // Deliberately silent: see above.
    }
    await signOut({ callbackUrl: "/login" });
  }

  return (
    <button
      type="button"
      onClick={handleSignOut}
      aria-label="Sign out"
      className={cn(
        className ??
          "flex h-9 w-9 items-center justify-center rounded-full border border-border text-foreground transition-colors hover:bg-surface-muted",
      )}
    >
      {children}
    </button>
  );
}
