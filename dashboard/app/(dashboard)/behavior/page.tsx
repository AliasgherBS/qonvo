"use client";

import {
  HoursSection,
  PersonaSection,
  TenantConfigPage,
  VoiceSection,
} from "@/components/settings/tenant-config";

/**
 * How the rep behaves towards a customer: who it sounds like, when it is
 * available, and whether it talks back. Nothing here is infrastructure.
 */
export default function BehaviorPage() {
  return (
    <TenantConfigPage
      title="Behavior"
      description="How your AI rep sounds, when it answers, and whether it replies with voice."
      fields={[
        "persona",
        "tone",
        "primary_language",
        "custom_instructions",
        "business_hours",
        "voice_reply_mode",
      ]}
    >
      {(props) => (
        <>
          <PersonaSection {...props} />
          <HoursSection {...props} />
          <VoiceSection {...props} />
        </>
      )}
    </TenantConfigPage>
  );
}
