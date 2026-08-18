"use client";

import {
  Activity,
  BarChart3,
  BookOpen,
  Building2,
  Inbox,
  Plug,
  Radio,
  SlidersHorizontal,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import type { Role } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * A bottom bar cannot hold the sidebar's nine grouped entries without becoming
 * unreadable, so this is the five most-used destinations. Everything else is
 * reachable from the account menu and from links on these pages.
 *
 * Behavior replaces the old Settings entry, since that is where most of what
 * Settings held now lives.
 */
const OWNER_ITEMS = [
  { href: "/inbox", label: "Inbox", icon: Inbox },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/behavior", label: "Behavior", icon: SlidersHorizontal },
  { href: "/integrations", label: "Apps", icon: Plug },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
];

const ADMIN_ITEMS = [
  { href: "/admin/tenants", label: "Tenants", icon: Building2 },
  { href: "/admin/fleet", label: "Fleet", icon: Radio },
  { href: "/admin/health", label: "Health", icon: Activity },
];

export function MobileNav({ role }: { role: Role }) {
  const pathname = usePathname();
  const items = role === "qonvo_admin" ? ADMIN_ITEMS : OWNER_ITEMS;

  return (
    <nav className="flex items-center justify-around border-t border-border bg-surface px-2 py-2 lg:hidden">
      {items.map(({ href, label, icon: Icon }) => {
        const active = pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex flex-col items-center gap-0.5 rounded-xl px-3 py-1.5 text-xs font-semibold",
              active ? "text-primary-strong" : "text-muted-foreground",
            )}
          >
            <Icon className="h-5 w-5" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
