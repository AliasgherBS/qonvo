"use client";

import { ArrowRight, Check, Lock } from "lucide-react";
import Link from "next/link";

import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { skills, type SkillInfo } from "@/lib/api/account";
import { useApi, useAuthToken } from "@/lib/use-api";
import { cn } from "@/lib/utils";

/**
 * What the rep can actually do (teardown P1).
 *
 * The Skills page promised "what your AI rep can do for a customer beyond
 * answering questions" and delivered a phone number, a payment details box and
 * one sentence pointing at Integrations. The eight real capabilities were named
 * nowhere in the dashboard, so an owner could not see what they bought and
 * could not tell which of it was waiting on a connection they had never made.
 *
 * The list is rendered from the server's registry, never from a copy of it
 * here: a hard-coded list is wrong the first time a skill is added, and it is
 * wrong silently. The gating (`requires_integration`, `requires_config_key`)
 * comes from the same metadata the pipeline uses to decide which tools the
 * model is offered, so what this page says and what the rep does cannot drift.
 *
 * Read-only, deliberately, for now. A switch here would need a per-skill write
 * endpoint that does not exist; showing one that does nothing would be the
 * finding this fixes, in miniature.
 */
export function SkillList() {
  const token = useAuthToken();
  const { data, loading, error, refetch } = useApi(() => skills.list({ token }), [token]);

  if (loading) {
    return (
      <div className="space-y-3">
        {[0, 1, 2, 3].map((i) => (
          <Card key={i}>
            <CardContent className="space-y-2 pt-5">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-3 w-3/4" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  if (error || !data) {
    return (
      <Card>
        <CardContent className="pt-5 text-sm text-muted-foreground">
          {error ?? "Could not load your skills."}
          <Button variant="outline" size="sm" className="ml-3" onClick={refetch}>
            Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  // Available first. The owner's question is "what does my rep do", and the
  // answer to that should not be interleaved with things it cannot do yet.
  // Stable within each group: the server's order is the registry's.
  const ready = data.filter((s) => s.available);
  const blocked = data.filter((s) => !s.available);

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h2 className="text-sm font-bold">
          Working now
          <span className="ml-2 font-normal text-muted-foreground">{ready.length}</span>
        </h2>
        {ready.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing is switched on yet. Everything below says what it needs.
          </p>
        ) : (
          ready.map((skill) => <SkillRow key={skill.key} skill={skill} />)
        )}
      </section>

      {blocked.length > 0 ? (
        <section className="space-y-2">
          <h2 className="text-sm font-bold">
            Needs one thing from you
            <span className="ml-2 font-normal text-muted-foreground">{blocked.length}</span>
          </h2>
          {blocked.map((skill) => (
            <SkillRow key={skill.key} skill={skill} />
          ))}
        </section>
      ) : null}
    </div>
  );
}

/**
 * Where an owner goes to unblock a skill.
 *
 * The gate is the server's own vocabulary (`google_calendar`,
 * `payment_details`), so the mapping lives here rather than being sent down:
 * which page a setting is on is a fact about this app, and the API should not
 * have to know the route table.
 */
function unblockHref(skill: SkillInfo): string | null {
  if (skill.requiresIntegration) return "/integrations";
  if (skill.requiresConfigKey === "payment_details") return "/business";
  return null;
}

function SkillRow({ skill }: { skill: SkillInfo }) {
  const href = skill.available ? null : unblockHref(skill);

  return (
    <div
      className={cn(
        "flex flex-wrap items-start gap-3 rounded-2xl border border-border bg-surface px-4 py-3",
        !skill.available && "bg-surface-muted",
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl",
          skill.available ? "bg-primary/15 text-primary-strong" : "bg-border text-muted-foreground",
        )}
      >
        {skill.available ? <Check className="h-4 w-4" /> : <Lock className="h-4 w-4" />}
      </span>

      <div className="min-w-0 flex-1">
        <p className="text-sm font-bold">{skill.label}</p>
        <p className="text-xs text-muted-foreground">{skill.description}</p>
      </div>

      {skill.available ? (
        <span className="text-xs font-semibold text-primary-strong">Available</span>
      ) : href ? (
        <Link
          href={href}
          className="flex items-center gap-1.5 text-xs font-semibold text-primary-strong underline-offset-2 hover:underline"
        >
          {skill.needs}
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      ) : (
        <span className="text-xs font-semibold text-muted-foreground">{skill.needs}</span>
      )}
    </div>
  );
}
