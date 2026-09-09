"use client";

import { Check, X } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Says whether a password will be accepted, before it is submitted (teardown X5).
 *
 * The policy was eight characters and nothing else, so `password1` and the
 * business's own name both passed. It is now twelve characters, no composition
 * rules, and a check against Have I Been Pwned -- which follows NIST 800-63B,
 * and matters here because complexity rules push people towards `Passw0rd!`
 * rather than towards a phrase.
 *
 * The breach check cannot happen in the browser: the whole point of the
 * k-anonymity lookup is that only five characters of the hash leave the
 * process holding the password, and doing it from a page would put the hash
 * prefix in the browser's network log for anything on the machine to read. So
 * this covers the rules it can see, and the server has the last word. The
 * meter's job is to stop somebody being told "too short" after filling in a
 * form, not to be the policy.
 */
export const MIN_PASSWORD_LENGTH = 12;

type Rule = { label: string; ok: boolean };

/** The rules a browser can honestly check. Kept in step with `app/core/passwords.py`. */
export function passwordRules(
  password: string,
  { email, businessName }: { email?: string; businessName?: string } = {},
): Rule[] {
  const lowered = password.toLowerCase();
  const tokens = [email?.split("@")[0], businessName]
    .filter(Boolean)
    .flatMap((value) => value!.toLowerCase().split(/[^a-z0-9]+/))
    .filter((piece) => piece.length >= 4);

  return [
    { label: `At least ${MIN_PASSWORD_LENGTH} characters`, ok: password.length >= MIN_PASSWORD_LENGTH },
    {
      label: "Not your business name or email",
      ok: tokens.length === 0 || !tokens.some((piece) => lowered.includes(piece)),
    },
    {
      label: "More than one or two different characters",
      ok: password.trim().length === 0 || new Set(password.trim()).size > 2,
    },
  ];
}

export function PasswordStrength({
  password,
  email,
  businessName,
  /** Server-side reasons, which include the breach check the browser cannot do. */
  serverReasons,
}: {
  password: string;
  email?: string;
  businessName?: string;
  serverReasons?: string[];
}) {
  // Nothing typed yet: a wall of red crosses before the first keystroke reads
  // as failure rather than as guidance.
  if (!password && !serverReasons?.length) {
    return (
      <p className="text-xs text-muted-foreground">
        Use at least {MIN_PASSWORD_LENGTH} characters. A short phrase is stronger than a
        mangled word, and easier to remember.
      </p>
    );
  }

  const rules = passwordRules(password, { email, businessName });
  const met = rules.filter((r) => r.ok).length;

  return (
    <div className="space-y-1.5">
      {/* One bar per rule rather than a score out of four. A score invites
          "how do I get to strong?", which the rules answer directly. */}
      <div className="flex gap-1" aria-hidden="true">
        {rules.map((rule, i) => (
          <span
            key={rule.label}
            className={cn(
              "h-1 flex-1 rounded-full transition-colors",
              i < met ? "bg-primary" : "bg-border",
            )}
          />
        ))}
      </div>
      <ul className="space-y-0.5">
        {rules.map((rule) => (
          <li
            key={rule.label}
            className={cn(
              "flex items-center gap-1.5 text-xs",
              rule.ok ? "text-muted-foreground" : "text-foreground",
            )}
          >
            {rule.ok ? (
              <Check className="h-3 w-3 shrink-0 text-primary-strong" />
            ) : (
              <X className="h-3 w-3 shrink-0 text-muted-foreground" />
            )}
            {rule.label}
          </li>
        ))}
        {serverReasons?.map((reason) => (
          <li key={reason} className="flex items-center gap-1.5 text-xs text-danger">
            <X className="h-3 w-3 shrink-0" />
            {reason}
          </li>
        ))}
      </ul>
    </div>
  );
}
