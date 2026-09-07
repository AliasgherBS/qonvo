"use client";

import {
  Activity,
  BarChart3,
  BookOpen,
  Building2,
  CreditCard,
  Gauge,
  Inbox,
  Plug,
  Radio,
  Smartphone,
  Sparkles,
  SlidersHorizontal,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/logo";
import type { Role } from "@/lib/api";
import { cn } from "@/lib/utils";
import { HelpMenu } from "@/components/help-menu";

/**
 * Grouped, not a flat list of nine.
 *
 * The organising split for the whole app: the business and its bot live here,
 * the person lives under the avatar menu in the topbar. That is why there is
 * no Profile or Password entry below.
 */
const NAV_GROUPS: { label?: string; items: { href: string; label: string; icon: typeof Inbox }[] }[] =
  [
    {
      items: [
        { href: "/inbox", label: "Inbox", icon: Inbox },
        { href: "/analytics", label: "Analytics", icon: BarChart3 },
      ],
    },
    {
      label: "AI rep",
      items: [
        { href: "/knowledge", label: "Knowledge", icon: BookOpen },
        { href: "/behavior", label: "Behavior", icon: SlidersHorizontal },
        { href: "/skills", label: "Skills", icon: Sparkles },
      ],
    },
    {
      label: "Setup",
      items: [
        { href: "/onboarding/connect", label: "WhatsApp", icon: Smartphone },
        { href: "/integrations", label: "Integrations", icon: Plug },
      ],
    },
    {
      label: "Workspace",
      items: [
        { href: "/business", label: "Business", icon: Building2 },
        { href: "/team", label: "Team", icon: Users },
        { href: "/billing", label: "Billing", icon: CreditCard },
      ],
    },
  ];

const ADMIN_NAV_ITEMS = [
  { href: "/admin/tenants", label: "Tenants", icon: Building2 },
  { href: "/admin/fleet", label: "Fleet Health", icon: Radio },
  { href: "/admin/health", label: "System Health", icon: Activity },
  { href: "/admin/usage", label: "Usage", icon: Gauge },
];

export function Sidebar({ role }: { role: Role }) {
  const pathname = usePathname();

  return (
    <aside className="hidden w-64 flex-col border-r border-border bg-surface px-4 py-6 lg:flex">
      <div className="px-2">
        <Logo />
      </div>

      <nav className="mt-8 flex flex-1 flex-col gap-6">
        {/* A qonvo_admin has no tenant, so the owner pages 403 for them. Show
            only the cross-tenant admin console. Owners get the owner nav. */}
        {role === "qonvo_admin" ? (
          <div className="flex flex-col gap-1">
            {ADMIN_NAV_ITEMS.map((item) => (
              <NavLink key={item.href} {...item} active={pathname.startsWith(item.href)} />
            ))}
          </div>
        ) : (
          NAV_GROUPS.map((group, i) => (
            <div key={group.label ?? i} className="flex flex-col gap-1">
              {group.label ? (
                <p className="px-3 pb-1 text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
                  {group.label}
                </p>
              ) : null}
              {group.items.map((item) => (
                <NavLink key={item.href} {...item} active={pathname.startsWith(item.href)} />
              ))}
            </div>
          ))
        )}
      </nav>

      <div className="space-y-2">
        <HelpMenu />
        <p className="px-3 text-xs text-muted-foreground">Never miss a customer.</p>
      </div>
    </aside>
  );
}

function NavLink({
  href,
  label,
  icon: Icon,
  active,
}: {
  href: string;
  label: string;
  icon: typeof Inbox;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      // The tour finds its targets by this, rather than by href. An attribute
      // says "something points at me" in the diff; a selector living in another
      // file goes stale silently the next time a route is renamed.
      data-tour={`nav:${href}`}
      className={cn(
        "flex items-center gap-3 rounded-full px-3 py-2 text-sm font-semibold transition-colors",
        active ? "bg-primary/15 text-primary-strong" : "text-foreground hover:bg-surface-muted",
      )}
    >
      <Icon className="h-4 w-4" />
      {label}
    </Link>
  );
}
