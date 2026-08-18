"use client";

import { LogOut, User } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { SignOutButton } from "@/components/sign-out-button";
import { ThemeToggle } from "@/components/theme-toggle";

/**
 * The person's corner of the app.
 *
 * The business and its bot live in the sidebar; everything about you lives
 * behind this avatar. That split is why Change Password no longer sits inside
 * the bot's configuration.
 */
export function AccountMenu({ userName, email }: { userName: string; email?: string | null }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const initial = (userName || email || "?").trim().charAt(0).toUpperCase();

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/15 text-sm font-bold text-primary-strong transition-transform active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="sr-only">Open account menu</span>
        {initial}
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-2 w-64 overflow-hidden rounded-2xl border border-border bg-surface shadow-xl"
        >
          <div className="border-b border-border px-4 py-3">
            <p className="truncate text-sm font-bold">{userName}</p>
            {email ? (
              <p className="truncate text-xs text-muted-foreground">{email}</p>
            ) : null}
          </div>

          <Link
            href="/account"
            role="menuitem"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2.5 px-4 py-2.5 text-sm font-semibold hover:bg-surface-muted"
          >
            <User className="h-4 w-4" />
            Account
          </Link>

          <div className="flex items-center justify-between border-t border-border px-4 py-2.5 text-sm font-semibold">
            <span>Theme</span>
            <ThemeToggle />
          </div>

          <div className="border-t border-border px-4 py-2.5">
            <SignOutButton className="flex w-full items-center gap-2.5 text-sm font-semibold text-danger">
              <LogOut className="h-4 w-4" />
              Sign out
            </SignOutButton>
          </div>
        </div>
      ) : null}
    </div>
  );
}
