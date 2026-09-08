"use client";

import {
  Activity,
  BarChart3,
  BookOpen,
  Building2,
  CreditCard,
  Inbox,
  MoreHorizontal,
  Plug,
  Radio,
  SlidersHorizontal,
  Smartphone,
  Sparkles,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import type { Role } from "@/lib/api";
import { canReach } from "@/lib/nav-access";
import { cn } from "@/lib/utils";

/**
 * The bottom bar, and everything it could not hold (teardown S1, S2).
 *
 * Two separate breakages. The bar was in normal flow rather than pinned, so on
 * the inbox it rendered at y=1114 of an 1,181 pixel document and on Behavior
 * or Billing -- several thousand pixels long -- navigation sat a very long way
 * past the end of the content. A bottom bar you have to scroll to is not a
 * bottom bar.
 *
 * And its own comment claimed everything else was "reachable from the account
 * menu", which contained Account, Theme and Sign out. So Billing, Team,
 * Business, Skills and WhatsApp could not be reached on a phone at all except
 * by typing the URL. Billing is where an owner goes when their rep has stopped
 * working, and the phone is what is in their hand.
 *
 * Four destinations plus More, rather than five destinations. The fifth slot
 * was buying one more shortcut at the cost of five pages being unreachable.
 */
type Item = { href: string; label: string; icon: typeof Inbox };

const PRIMARY: Item[] = [
  { href: "/inbox", label: "Inbox", icon: Inbox },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/behavior", label: "Behavior", icon: SlidersHorizontal },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
];

/** Everything the bar cannot hold. Billing is first on purpose. */
const MORE: Item[] = [
  { href: "/billing", label: "Billing", icon: CreditCard },
  { href: "/onboarding/connect", label: "WhatsApp", icon: Smartphone },
  { href: "/integrations", label: "Apps", icon: Plug },
  { href: "/skills", label: "Skills", icon: Sparkles },
  { href: "/business", label: "Business", icon: Building2 },
  { href: "/team", label: "Team", icon: Users },
];

const ADMIN_PRIMARY: Item[] = [
  { href: "/admin/tenants", label: "Tenants", icon: Building2 },
  { href: "/admin/fleet", label: "Fleet", icon: Radio },
  { href: "/admin/health", label: "Health", icon: Activity },
];

export function MobileNav({ role }: { role: Role }) {
  const pathname = usePathname();
  const [moreOpen, setMoreOpen] = useState(false);

  // A destination that is open when you navigate stays open over the new page,
  // which reads as the tap not having worked.
  useEffect(() => setMoreOpen(false), [pathname]);

  useEffect(() => {
    if (!moreOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMoreOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [moreOpen]);

  const isAdmin = role === "qonvo_admin";
  const primary = (isAdmin ? ADMIN_PRIMARY : PRIMARY).filter((i) => canReach(role, i.href));
  // Account, Theme and Sign out stay behind the avatar in the top bar, which
  // is reachable on a phone. Every entry here is owner-only, so a staff seat
  // gets no More button at all rather than a sheet holding one duplicate.
  const more = isAdmin ? [] : MORE.filter((i) => canReach(role, i.href));

  return (
    <>
      {moreOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close menu"
            onClick={() => setMoreOpen(false)}
            className="absolute inset-0 bg-black/40"
          />
          <div
            role="menu"
            // Above the bar rather than over it. The bar is z-50 and this is
            // z-40, so it stays visible and tappable while the sheet is open,
            // and the sheet reads as belonging to it. An earlier version sat
            // at bottom-0 with padding reserved for the bar, which just put
            // blank space over a hidden bar -- verified in a browser at
            // 390x844, which is the only way to catch that.
            //
            // 4.25rem is the bar's measured height; its own padding adds the
            // safe-area inset on top, so this has to as well.
            className="absolute inset-x-0 bottom-[calc(4.25rem+env(safe-area-inset-bottom))] max-h-[70vh] overflow-y-auto rounded-t-3xl border border-border bg-surface pb-2 shadow-2xl"
          >
            <div className="flex items-center justify-between px-5 py-4">
              <p className="text-sm font-extrabold">More</p>
              <button
                type="button"
                onClick={() => setMoreOpen(false)}
                className="flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground hover:bg-surface-muted"
              >
                <span className="sr-only">Close</span>
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="pb-2">
              {more.map(({ href, label, icon: Icon }) => (
                <Link
                  key={href}
                  href={href}
                  role="menuitem"
                  onClick={() => setMoreOpen(false)}
                  className={cn(
                    "flex items-center gap-3 px-5 py-3 text-sm font-semibold hover:bg-surface-muted",
                    pathname.startsWith(href) && "text-primary-strong",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </Link>
              ))}
            </div>
          </div>
        </div>
      ) : null}

      {/* fixed, not in flow. `safe-area-inset-bottom` keeps the row clear of
          the iOS home indicator, which otherwise eats the bottom of the icons. */}
      <nav className="fixed inset-x-0 bottom-0 z-50 flex items-center justify-around border-t border-border bg-surface px-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))] pt-2 lg:hidden">
        {primary.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex flex-col items-center gap-0.5 rounded-xl px-3 py-1.5 text-xs font-semibold",
              pathname.startsWith(href) ? "text-primary-strong" : "text-muted-foreground",
            )}
          >
            <Icon className="h-5 w-5" />
            {label}
          </Link>
        ))}

        {more.length > 0 ? (
          <button
            type="button"
            onClick={() => setMoreOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={moreOpen}
            className={cn(
              "flex flex-col items-center gap-0.5 rounded-xl px-3 py-1.5 text-xs font-semibold",
              moreOpen || more.some((i) => pathname.startsWith(i.href))
                ? "text-primary-strong"
                : "text-muted-foreground",
            )}
          >
            <MoreHorizontal className="h-5 w-5" />
            More
          </button>
        ) : null}
      </nav>
    </>
  );
}
