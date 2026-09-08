"use client";

import {
  BusinessNameSection,
  ContactSection,
  HoursSection,
  PaymentsSection,
  TenantConfigPage,
  TimezoneSection,
} from "@/components/settings/tenant-config";

/**
 * The facts about the business, in one place (teardown V2, P2).
 *
 * They were spread over four pages and this one held only the name, which made
 * it a whole navigation entry for a single text field. Opening hours were on
 * Behavior, the owner's contact number and the payment details were on Skills,
 * and the timezone was inside the Google Calendar card on Integrations, where a
 * tenant with no Google account could not reach it at all. None of that
 * division followed from anything an owner believes about their own business,
 * and the timezone bug was a direct consequence of it: the one setting that
 * governs both opening hours and bookings lived inside an optional integration.
 *
 * The test for what belongs here is whether a new employee would need to be
 * told it. Where we are, when we open, how to pay us, who to call. How the rep
 * *talks* is Behavior; what it can *do* is Skills.
 *
 * The engine picker used to live here behind a disclosure. It is gone from the
 * owner-facing UI: choosing a model is not a decision a business owner is
 * equipped to make, and every wrong answer costs us either quality or money.
 * `llm_provider` and `llm_model` remain in the API, the database and the admin
 * console; `fields` does not name them, so this page never sends them and the
 * API's `exclude_unset` leaves whatever is stored alone.
 */
export default function BusinessPage() {
  return (
    <TenantConfigPage
      title="Business"
      description="The facts about your business. Your rep works from these, and so do your bookings."
      fields={[
        "business_name",
        "timezone",
        "owner_alert_number",
        "notify_on_handoff",
        "business_hours",
        "payment_details",
      ]}
    >
      {(props) => (
        <>
          <BusinessNameSection {...props} />
          {/* Above the hours, because the hours are read in this zone and the
              order says so. The same value governs every booking, which is why
              it is not next to only one of its two consumers any more. */}
          <TimezoneSection {...props} />
          <ContactSection {...props} />
          <HoursSection {...props} />
          <PaymentsSection {...props} />
        </>
      )}
    </TenantConfigPage>
  );
}
