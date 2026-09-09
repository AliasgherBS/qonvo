import { redirect } from "next/navigation";

import { EnvBanner } from "@/components/admin/env-banner";
import { auth } from "@/auth";

// Middleware already blocks non-admins from /admin/*; this is the second net
// (§3 "defense in depth, day one" - app-layer scoping backs the perimeter check).
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();

  if (session?.user?.role !== "qonvo_admin") {
    redirect("/inbox");
  }

  return (
    <div className="space-y-4">
      {/* Which stack are these buttons pointed at? The production and staging
          consoles are pixel-identical and the actions on them are
          irreversible. */}
      <EnvBanner />
      {children}
    </div>
  );
}
