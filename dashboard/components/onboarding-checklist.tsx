"use client";

import { CheckCircle2, Circle, Rocket } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { onboarding } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * First-run "get to live" checklist. Derived server-side from real data
 * (business info, WhatsApp link, knowledge, integrations). Hides itself once
 * every required step is done so it doesn't nag established tenants.
 */
export function OnboardingChecklist() {
  const token = useAuthToken();
  const { data } = useApi(() => onboarding.get({ token }), [token]);

  if (!data || data.complete) return null;

  const doneCount = data.steps.filter((s) => s.done).length;

  return (
    <Card className="border-primary/30 bg-primary/5">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Rocket className="h-5 w-5 text-primary" />
          <div>
            <CardTitle>Finish setting up</CardTitle>
            <CardDescription>
              {doneCount} of {data.steps.length} done — complete these to go live.
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-2.5">
        {data.steps.map((step) => (
          <div key={step.key} className="flex items-start gap-3">
            {step.done ? (
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" />
            ) : (
              <Circle className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
            )}
            <div>
              <p className={`text-sm font-semibold ${step.done ? "text-muted-foreground line-through" : ""}`}>
                {step.label}
                {!step.required ? <span className="ml-2 text-xs font-normal">(optional)</span> : null}
              </p>
              {!step.done ? (
                <p className="text-xs text-muted-foreground">{step.description}</p>
              ) : null}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
