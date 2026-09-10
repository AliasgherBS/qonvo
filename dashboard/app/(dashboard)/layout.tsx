import { redirect } from "next/navigation";

import { ConnectionBanner } from "@/components/connection-banner";
import { MobileNav } from "@/components/mobile-nav";
import { Sidebar } from "@/components/sidebar";
import { Topbar } from "@/components/topbar";
import { ProductTour } from "@/components/product-tour";
import { TrialBanner } from "@/components/trial-banner";
import { VerifyEmailBanner } from "@/components/verify-email-banner";
import { auth } from "@/auth";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();

  // Middleware already redirects unauthenticated requests, but a server
  // layout should never trust that alone - fail closed if it's missing.
  if (!session?.user) {
    redirect("/login");
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar role={session.user.role} />

      {/* min-w-0 is load-bearing, and its absence was audit finding H3.
          A flex item defaults to min-width:auto, which means "never shrink
          below your content". So this column grew to whatever the widest table
          inside it wanted, and /knowledge rendered 922px wide on a 390px phone
          with the rep switch, the bell and the avatar all off-screen.

          The tables were already wrapped in overflow-x:auto. Those wrappers
          were correct and completely inert: a scroll container can only scroll
          if something upstream has bounded it, and nothing had. Same family as
          the inbox height bug -- a container that cannot do its job because an
          ancestor never gave it a size. */}
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar
          tenantName={session.user.tenantName}
          userName={session.user.name ?? session.user.email ?? "You"}
          email={session.user.email}
          role={session.user.role}
        />

        {/* pb-28 on mobile: the bottom bar is fixed now, so it no longer
            reserves its own space in the flex column and would otherwise cover
            the last of the scrollable content (teardown S1). */}
        <main className="min-w-0 flex-1 overflow-y-auto p-4 pb-28 lg:p-8">
          {/* Owner-only banners (a cross-tenant admin has no tenant/session). */}
          {session.user.role === "qonvo_admin" ? null : (
            <>
              {/* Above the trial banner: an unconfirmed address blocks the
                  next step, so it outranks a countdown. */}
              <VerifyEmailBanner />
              <TrialBanner />
              <ConnectionBanner role={session.user.role} />
              {/* The rep switch used to render here, as a full-width card
                  above every page's title. It lives in the top bar now
                  (teardown S3): still global, still one click, and no longer
                  charging every page ninety pixels for it. */}
              {/* Runs once per browser and describes the sidebar and the
                  switch, so it belongs in the layout rather than on a page:
                  both of its targets are in the shell. */}
              <ProductTour />
            </>
          )}
          {children}
        </main>

        <MobileNav role={session.user.role} />
      </div>
    </div>
  );
}
