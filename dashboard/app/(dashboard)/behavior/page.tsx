"use client";

import { ImproveInstructionsSection } from "@/components/behavior/improve-instructions";
import {
  PersonaSection,
  TenantConfigPage,
  VoiceSection,
} from "@/components/settings/tenant-config";

/**
 * How the rep talks. Persona, tone, language, the rules it follows, and whether
 * it answers with a voice note.
 *
 * The opening hours used to be here too and have moved to Business (teardown
 * V2): when a business is open is a fact about the business, not a property of
 * how its rep speaks, and the hours and the bookings read the same clock.
 */
export default function BehaviorPage() {
  return (
    <TenantConfigPage
      title="Behavior"
      description="How your AI rep sounds, what rules it follows, and whether it replies with voice."
      // reply_language_mode was missing from this list while VoiceSection has
      // always edited it, so choosing a reply language did nothing and said
      // nothing: the field was dropped from the payload and the page still
      // toasted "Saved". Every field a section on this page can change has to
      // be named here.
      fields={[
        "persona",
        "tone",
        "primary_language",
        "custom_instructions",
        "voice_reply_mode",
        "reply_language_mode",
      ]}
    >
      {(props) => (
        <>
          <PersonaSection {...props} />
          {/* Directly under the field it reviews, and it edits the same draft
              object, so accepting a suggestion just makes the page dirty and
              the page's own Save bar does the saving. Nothing about this
              control writes to the API. */}
          <ImproveInstructionsSection {...props} />
          <VoiceSection {...props} />
        </>
      )}
    </TenantConfigPage>
  );
}
