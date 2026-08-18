"use client";

import { signOut } from "next-auth/react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

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
  return (
    <button
      type="button"
      onClick={() => signOut({ callbackUrl: "/login" })}
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
