"use client";

import { SkillList } from "@/components/settings/skill-list";

/**
 * The capability list, and nothing else (teardown V4, P1).
 *
 * This page used to mix three unrelated concerns and name itself after the one
 * it did not contain: a WhatsApp number for alerts (a way to reach a person),
 * an alert toggle (a notification preference) and payment details (a fact the
 * rep reads out to customers). All three are facts about the business and have
 * moved to Business. What is left is what the name always promised.
 *
 * No save button, because there is nothing here to save. Turning a skill off is
 * a real want and needs a per-skill write endpoint; a switch that did nothing
 * would be the same finding again.
 */
export default function SkillsPage() {
  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Skills</h1>
        <p className="text-sm text-muted-foreground">
          What your AI rep can do for a customer beyond answering questions. Anything waiting on
          you says so, and links to the one place that fixes it. If your own instructions look
          like they forbid something that is connected and working, the row says so too.
        </p>
      </div>

      <SkillList />
    </div>
  );
}
