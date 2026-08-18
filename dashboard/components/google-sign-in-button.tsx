"use client";

import { signIn } from "next-auth/react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

/**
 * "Continue with Google" - identity only.
 *
 * Renders nothing unless NEXT_PUBLIC_GOOGLE_AUTH_ENABLED is set, so a deployment
 * without Google credentials shows a working password form rather than a button
 * that dead-ends on an Auth.js provider error.
 *
 * Same Google client as the Calendar/Sheets integrations, but a separate consent:
 * a new user is asked only for their identity here. Calendar permission is
 * requested later, from Integrations, once they actually turn booking on.
 */
export function GoogleSignInButton({
  callbackUrl = "/inbox",
  label = "Continue with Google",
}: {
  callbackUrl?: string;
  label?: string;
}) {
  const [loading, setLoading] = useState(false);

  if (process.env.NEXT_PUBLIC_GOOGLE_AUTH_ENABLED !== "true") return null;

  return (
    <div className="space-y-4">
      <Button
        type="button"
        variant="outline"
        className="w-full"
        disabled={loading}
        onClick={() => {
          setLoading(true);
          void signIn("google", { callbackUrl });
        }}
      >
        <GoogleGlyph />
        {loading ? "Redirecting…" : label}
      </Button>

      <div className="flex items-center gap-3">
        <span className="h-px flex-1 bg-border" />
        <span className="text-xs uppercase tracking-wide text-muted-foreground">or</span>
        <span className="h-px flex-1 bg-border" />
      </div>
    </div>
  );
}

/**
 * Google's four-colour mark. Inlined so it needs no network request.
 *
 * These hexes are Google's own brand colours and are mandated by their
 * sign-in branding guidelines, so they are the one place in the app allowed
 * to bypass our token system.
 *
 * brand-ok: no-raw-hex
 */
function GoogleGlyph() {
  return (
    <svg className="mr-2 h-4 w-4" viewBox="0 0 18 18" aria-hidden="true">
      <path
        // brand-ok: no-raw-hex
        fill="#4285F4"
        d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.71-1.57 2.68-3.89 2.68-6.62Z"
      />
      <path
        // brand-ok: no-raw-hex
        fill="#34A853"
        d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.34A8.99 8.99 0 0 0 9 18Z"
      />
      <path
        // brand-ok: no-raw-hex
        fill="#FBBC05"
        d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.94H.96a8.99 8.99 0 0 0 0 8.12l3.01-2.34Z"
      />
      <path
        // brand-ok: no-raw-hex
        fill="#EA4335"
        d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.59C13.46.89 11.43 0 9 0A8.99 8.99 0 0 0 .96 4.94l3.01 2.34C4.68 5.16 6.66 3.58 9 3.58Z"
      />
    </svg>
  );
}
