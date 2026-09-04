import { AccountMenu } from "@/components/account-menu";
import { EnvBadge } from "@/components/env-badge";
import { NotificationsBell } from "@/components/notifications-bell";
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
  email,
  role,
}: {
  tenantName: string;
  userName: string;
  email?: string | null;
  role: Role;
}) {
  return (
    <header className="flex h-16 items-center justify-between border-b border-border bg-surface px-4 lg:px-6">
      <div className="flex items-center gap-3">
        <p className="text-sm font-bold tracking-tight">{tenantName}</p>
        <Badge tone={role === "qonvo_admin" ? "info" : "default"}>{ROLE_LABEL[role]}</Badge>
        {/* Renders nothing in production; shouts on staging and local. */}
        <EnvBadge />
      </div>

      <div className="flex items-center gap-3">
        {/* Notifications are tenant-scoped; a cross-tenant admin has no tenant,
            so the poll would 403. Only owners/staff get the bell. */}
        {role === "qonvo_admin" ? null : <NotificationsBell />}
        {/* Theme and sign-out moved inside the account menu: they are settings
            about the person, not about the workspace. */}
        <AccountMenu userName={userName} email={email} />
      </div>
    </header>
  );
}
