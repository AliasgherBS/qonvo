"use client";

import { Activity } from "lucide-react";
import { useEffect } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { adminHealth, type SystemHealth } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";

const num = new Intl.NumberFormat("en-US");
const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 4 });

/** Sum every label-set of a counter into one total. */
function total(h: SystemHealth, name: string): number {
  const fields = h.metrics.counters[name];
  return fields ? Object.values(fields).reduce((a, b) => a + b, 0) : 0;
}

/** Break a counter down by one label (e.g. gate="rate_limited" → { rate_limited: 3 }). */
function byLabel(h: SystemHealth, name: string, label: string): Record<string, number> {
  const fields = h.metrics.counters[name] ?? {};
  const out: Record<string, number> = {};
  for (const [key, value] of Object.entries(fields)) {
    const m = key.match(new RegExp(`${label}="([^"]*)"`));
    if (m) out[m[1]] = (out[m[1]] ?? 0) + value;
  }
  return out;
}

export default function AdminHealthPage() {
  const token = useAuthToken();
  const { data, loading, error, refetch } = useApi(() => adminHealth.get({ token }), [token]);

  // Live-ish: refresh every 15s while the page is open.
  useEffect(() => {
    const id = setInterval(refetch, 15_000);
    return () => clearInterval(id);
  }, [refetch]);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">System health</h1>
          <p className="text-sm text-muted-foreground">
            Live readiness and pipeline metrics. Full graphs + alerts live in Grafana
            (<code className="text-xs">127.0.0.1:3003</code>, monitoring profile).
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refetch}>
          Refresh
        </Button>
      </div>

      {loading && !data ? (
        <div className="grid gap-3 sm:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-24 rounded-2xl" />
          ))}
        </div>
      ) : error || !data ? (
        <div className="rounded-2xl border border-border bg-surface p-5">
          <EmptyState
            icon={<Activity className="h-5 w-5" />}
            title="Couldn't load health"
            description={error ?? "No data."}
            action={
              <Button variant="outline" size="sm" onClick={refetch}>
                Retry
              </Button>
            }
          />
        </div>
      ) : (
        <HealthBody h={data} />
      )}
    </div>
  );
}

function HealthBody({ h }: { h: SystemHealth }) {
  const avgLatency = h.metrics.histograms["qonvo_pipeline_duration_seconds"]?.avg ?? 0;
  const gates = byLabel(h, "qonvo_pipeline_gate_total", "gate");
  const skills = byLabel(h, "qonvo_skill_invocations_total", "skill");

  const tiles = [
    { label: "Messages processed", value: num.format(total(h, "qonvo_messages_processed_total")) },
    { label: "Replies sent", value: num.format(total(h, "qonvo_replies_sent_total")) },
    { label: "LLM cost", value: usd.format(total(h, "qonvo_llm_cost_usd_total")) },
    { label: "LLM tokens", value: num.format(total(h, "qonvo_llm_tokens_total")) },
    { label: "Voice seconds", value: num.format(total(h, "qonvo_voice_seconds_total")) },
    { label: "Avg turn latency", value: `${avgLatency.toFixed(2)}s` },
  ];

  const errors = [
    { label: "Provider errors", value: total(h, "qonvo_provider_errors_total") },
    { label: "WhatsApp send failures", value: total(h, "qonvo_whatsapp_send_failures_total") },
    { label: "Job failures", value: total(h, "qonvo_job_failures_total") },
    { label: "Webhook 401s", value: total(h, "qonvo_webhook_unauthorized_total") },
  ];

  return (
    <div className="space-y-6">
      {/* Readiness */}
      <div className="rounded-2xl border border-border bg-surface p-5">
        <div className="mb-3 flex items-center gap-2">
          <span className="text-sm font-bold">Readiness</span>
          <Badge tone={h.ready ? "success" : "danger"}>{h.ready ? "healthy" : "degraded"}</Badge>
        </div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(h.checks).map(([dep, state]) => (
            <Badge key={dep} tone={state === "ok" ? "success" : "danger"}>
              {dep}: {state}
            </Badge>
          ))}
        </div>
      </div>

      {/* Throughput / cost tiles */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-2xl border border-border bg-surface p-5">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t.label}</p>
            <p className="mt-1 text-2xl font-extrabold tracking-tight">{t.value}</p>
          </div>
        ))}
      </div>

      {/* Errors */}
      <div>
        <h2 className="mb-2 text-sm font-bold uppercase tracking-wider text-muted-foreground">Errors (since start)</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {errors.map((e) => (
            <div key={e.label} className="rounded-2xl border border-border bg-surface p-4">
              <p className="text-xs text-muted-foreground">{e.label}</p>
              <p className={`mt-1 text-xl font-bold ${e.value > 0 ? "text-danger" : ""}`}>{num.format(e.value)}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Gate hits + skills breakdowns */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Breakdown title="Gate hits by reason" data={gates} empty="No turns gated yet." />
        <Breakdown title="Skill invocations" data={skills} empty="No skills called yet." />
      </div>
    </div>
  );
}

function Breakdown({ title, data, empty }: { title: string; data: Record<string, number>; empty: string }) {
  const rows = Object.entries(data).sort((a, b) => b[1] - a[1]);
  return (
    <div className="rounded-2xl border border-border bg-surface p-5">
      <h3 className="mb-3 text-sm font-bold">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="space-y-1.5 text-sm">
          {rows.map(([key, value]) => (
            <li key={key} className="flex items-center justify-between">
              <span className="text-muted-foreground">{key}</span>
              <span className="font-semibold">{num.format(value)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
