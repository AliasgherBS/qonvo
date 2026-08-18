"use client";

import Link from "next/link";

import {
  EscalationSection,
  PaymentsSection,
  TenantConfigPage,
} from "@/components/settings/tenant-config";
import { Card, CardContent } from "@/components/ui/card";

/**
 * Things the rep can do, as opposed to how it sounds. Handover lives here
 * rather than under Settings because handing a chat to a person is an action
 * the bot takes, and it pairs with the human_handoff skill that drives it.
 *
 * Booking and sheet logging are configured by connecting Google, so this page
 * points at Integrations rather than duplicating those controls.
 */
export default function SkillsPage() {
  return (
    <TenantConfigPage
      title="Skills"
      description="What your AI rep can do for a customer beyond answering questions."
      fields={["owner_alert_number", "notify_on_handoff", "payment_details"]}
    >
      {(props) => (
        <>
          <EscalationSection {...props} />
          <PaymentsSection {...props} />

          <Card>
            <CardContent className="pt-5 text-sm text-muted-foreground">
              Booking, order capture and lead logging switch on when you connect Google.{" "}
              <Link href="/integrations" className="font-semibold text-primary hover:underline">
                Go to Integrations
              </Link>
              .
            </CardContent>
          </Card>
        </>
      )}
    </TenantConfigPage>
  );
}
