import { BarChart3 } from "lucide-react";

import { EmptyState } from "@/components/ui/empty-state";

// Analytics isn't part of the Phase 1C backend contract yet (no
// /api/analytics/* route exists) — this stays a placeholder until that
// lands, rather than guessing at an endpoint shape.
export default function AnalyticsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Analytics</h1>
        <p className="text-sm text-muted-foreground">
          Volume, speed, and outcomes — proof your AI rep is pulling its weight.
        </p>
      </div>

      <EmptyState
        icon={<BarChart3 className="h-5 w-5" />}
        title="Analytics is coming soon"
        description="Volume, response time, and handoff stats will show up here once the analytics API ships."
      />
    </div>
  );
}
