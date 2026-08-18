"use client";

import {
  BusinessNameSection,
  ModelSection,
  TenantConfigPage,
} from "@/components/settings/tenant-config";

/** Workspace-level settings. Engine config sits here, behind a disclosure. */
export default function BusinessPage() {
  return (
    <TenantConfigPage
      title="Business"
      description="Your workspace name, and the engine settings behind it."
      fields={["business_name", "llm_provider", "llm_model"]}
    >
      {(props) => (
        <>
          <BusinessNameSection {...props} />
          <ModelSection {...props} />
        </>
      )}
    </TenantConfigPage>
  );
}
