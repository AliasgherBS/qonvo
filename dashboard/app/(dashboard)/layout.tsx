import { redirect } from "next/navigation";

import { ConnectionBanner } from "@/components/connection-banner";
import { MobileNav } from "@/components/mobile-nav";
import { Sidebar } from "@/components/sidebar";
import { Topbar } from "@/components/topbar";
import { TrialBanner } from "@/components/trial-banner";
import { auth } from "@/auth";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();

  // Middleware already redirects unauthenticated requests, but a server
  // layout should never trust that alone — fail closed if it's missing.
  if (!session?.user) {
    redirect("/login");
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar role={session.user.role} />

      <div className="flex flex-1 flex-col">
        <Topbar
          tenantName={session.user.tenantName}
          userName={session.user.name ?? session.user.email ?? "You"}
          role={session.user.role}
        />

        <main className="flex-1 overflow-y-auto p-4 lg:p-8">
          {/* Owner-only banners (a cross-tenant admin has no tenant/session). */}
          {session.user.role === "qonvo_admin" ? null : (
            <>
              <TrialBanner />
              <ConnectionBanner />
            </>
          )}
          {children}
        </main>

        <MobileNav role={session.user.role} />
      </div>
    </div>
  );
}
