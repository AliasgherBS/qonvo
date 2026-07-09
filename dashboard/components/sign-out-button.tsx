"use client";

import { signOut } from "next-auth/react";
import type { ReactNode } from "react";

export function SignOutButton({ children }: { children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={() => signOut({ callbackUrl: "/login" })}
      aria-label="Sign out"
      className="flex h-9 w-9 items-center justify-center rounded-full border border-border text-foreground transition-colors hover:bg-surface-muted"
    >
      {children}
    </button>
  );
}
