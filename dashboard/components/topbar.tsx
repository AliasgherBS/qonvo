import { LogOut } from "lucide-react";

import { SignOutButton } from "@/components/sign-out-button";
import { ThemeToggle } from "@/components/theme-toggle";
import { Badge } from "@/components/ui/badge";
import type { Role } from "@/lib/api";

const ROLE_LABEL: Record<Role, string> = {
  owner: "Owner",
  staff: "Staff",
  qonvo_admin: "Qonvo Admin",
};

export function Topbar({
  tenantName,
  userName,
  role,
}: {
  tenantName: string;
  userName: string;
  role: Role;
}) {
  return (
    <header className="flex h-16 items-center justify-between border-b border-border bg-surface px-4 lg:px-6">
      <div className="flex items-center gap-3">
        <p className="text-sm font-bold tracking-tight">{tenantName}</p>
        <Badge tone={role === "qonvo_admin" ? "info" : "default"}>{ROLE_LABEL[role]}</Badge>
      </div>

      <div className="flex items-center gap-3">
        <span className="hidden text-sm text-muted-foreground sm:inline">{userName}</span>
        <ThemeToggle />
        <SignOutButton>
          <LogOut className="h-4 w-4" />
        </SignOutButton>
      </div>
    </header>
  );
}
