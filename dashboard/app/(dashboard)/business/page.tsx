"use client";

import {
  BusinessNameSection,
  TenantConfigPage,
  TimezoneSection,
} from "@/components/settings/tenant-config";

/**
 * Workspace-level settings.
 *
 * The engine picker used to live here behind a disclosure. It is gone from the
 * owner-facing UI: choosing a model is not a decision a business owner is
 * equipped to make, and every wrong answer costs us either quality or money.
 * The platform default is the supported configuration.
 *
 * `llm_provider` and `llm_model` remain in the API and the database, and remain
 * editable from the admin console, because pinning one tenant to a specific
 * model is genuinely useful during an incident. `fields` no longer names them,
 * so this page does not send them and the API's `exclude_unset` leaves whatever
 * is stored alone.
 */
export default function BusinessPage() {
  return (
    <TenantConfigPage
      title="Business"
      description="Your workspace name and the clock your rep works to."
      // Not business_hours. This page does not render the opening hours, so
      // sending them would save whatever it happened to load -- which is the
      // cross-page clobber the `fields` mechanism exists to prevent. The
      // worker prefers the timezone column and reads the copy inside that JSON
      // only as a fallback, so the two do not need to be written together.
      fields={["business_name", "timezone"]}
    >
      {(props) => (
        <>
          <BusinessNameSection {...props} />
          {/* The timezone lives here rather than beside the opening hours,
              because the same value governs every booking. Keeping it next to
              only one of its two consumers is how it ended up buried inside
              the optional Google Calendar card. */}
          <TimezoneSection {...props} />
        </>
      )}
    </TenantConfigPage>
  );
}
