import { AccountMenu } from "@/components/account-menu";
import { EnvBadge } from "@/components/env-badge";
import { NotificationsBell } from "@/components/notifications-bell";
import { RepSwitch } from "@/components/rep-switch";
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
      {/* min-w-0 and truncate, because the right-hand cluster grew a rep
          switch: without them a long business name pushes the controls off a
          390px screen instead of being cut. The role badge is the least useful
          thing here on a phone, so it is the one that goes. */}
      <div className="flex min-w-0 items-center gap-3">
        <p className="truncate text-sm font-bold tracking-tight">{tenantName}</p>
        <Badge
          tone={role === "qonvo_admin" ? "info" : "default"}
          className="hidden sm:inline-flex"
        >
          {ROLE_LABEL[role]}
        </Badge>
        {/* Renders nothing in production; shouts on staging and local. */}
        <EnvBadge />
      </div>

      <div className="flex shrink-0 items-center gap-3">
        {/* The rep's on/off switch (teardown S3). It used to be a full-width
            card above the content on all thirteen pages, which taxed every H1
            by ninety pixels on desktop and a hundred and thirty on a phone.
            Here it is still global and still one click.

            Owner-only: switching the rep off silences it for the whole
            workspace, so PUT /api/activation refuses a staff seat and the
            control would only ever toast an error. */}
        {role === "owner" ? <RepSwitch /> : null}
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
