"use client";

import { BusinessNameSection, TenantConfigPage } from "@/components/settings/tenant-config";

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
      description="Your workspace name."
      fields={["business_name"]}
    >
      {(props) => <BusinessNameSection {...props} />}
    </TenantConfigPage>
  );
}
