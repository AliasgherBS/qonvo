"use client";

import {
  BarChart3,
  BookOpen,
  Building2,
  Gauge,
  Inbox,
  Plug,
  Radio,
  Settings,
  Smartphone,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/logo";
import type { Role } from "@/lib/api";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/inbox", label: "Inbox", icon: Inbox },
  { href: "/onboarding/connect", label: "WhatsApp", icon: Smartphone },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/integrations", label: "Integrations", icon: Plug },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
];

const ADMIN_NAV_ITEMS = [
  { href: "/admin/tenants", label: "Tenants", icon: Building2 },
  { href: "/admin/fleet", label: "Fleet Health", icon: Radio },
  { href: "/admin/usage", label: "Usage", icon: Gauge },
];

export function Sidebar({ role }: { role: Role }) {
  const pathname = usePathname();

  return (
    <aside className="hidden w-64 flex-col border-r border-border bg-surface px-4 py-6 lg:flex">
      <div className="px-2">
        <Logo />
      </div>

      <nav className="mt-8 flex flex-1 flex-col gap-1">
        {/* A qonvo_admin has no tenant, so the owner pages 403 for them — show
            only the cross-tenant admin console. Owners get the owner nav. */}
        {role === "qonvo_admin"
          ? ADMIN_NAV_ITEMS.map((item) => (
              <NavLink key={item.href} {...item} active={pathname.startsWith(item.href)} />
            ))
          : NAV_ITEMS.map((item) => (
              <NavLink key={item.href} {...item} active={pathname.startsWith(item.href)} />
            ))}
      </nav>

      <p className="px-3 text-xs text-muted-foreground">Never miss a customer.</p>
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
