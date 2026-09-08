/**
 * The person's own account, and the skill list.
 *
 * A separate module rather than more of `lib/api.ts`, which is past a thousand
 * lines and is the one file every concurrent change collides in. `apiFetch`
 * and `CallOpts` come from there; everything new lives here.
 *
 * Grouped by what the caller is doing rather than by which router serves it:
 * the second factor and "sign out everywhere" are Account-page concerns even
 * though they are `/api/auth` routes, and the skill list is a Skills-page
 * concern even though it is served by the config router.
 */

import { apiFetch, type CallOpts } from "@/lib/api";

// ---------------------------------------------------------------------------
// Profile (teardown V5)
// ---------------------------------------------------------------------------

interface ProfileDto {
  email: string;
  full_name: string | null;
  role: string | null;
  totp_enabled: boolean;
}

export interface Profile {
  email: string;
  fullName: string;
  role: string | null;
  /** Whether a second factor is already in force for this person. */
  totpEnabled: boolean;
}

function mapProfile(dto: ProfileDto): Profile {
  return {
    email: dto.email,
    // Never null past this boundary: the field it feeds is a controlled input,
    // and a null there makes React switch it to uncontrolled mid-life.
    fullName: dto.full_name ?? "",
    role: dto.role,
    totpEnabled: dto.totp_enabled,
  };
}

export const profile = {
  get: (opts: CallOpts = {}) =>
    apiFetch<ProfileDto>("/api/account/profile", opts).then(mapProfile),

  setName: (fullName: string, opts: CallOpts = {}) =>
    apiFetch<ProfileDto>("/api/account/profile", {
      method: "PATCH",
      body: { full_name: fullName },
      ...opts,
    }).then(mapProfile),
};

// ---------------------------------------------------------------------------
// Second factor and session control (teardown V6)
// ---------------------------------------------------------------------------

export interface TotpEnrolment {
  /** Base32, to be typed into an authenticator app by hand. */
  secret: string;
  /** `otpauth://totp/...`. Tapping it on a phone opens the app directly. */
  provisioningUri: string;
}

export const security = {
  /**
   * Issue a pending secret. Re-callable: starting again replaces it, which is
   * what somebody does when they lose the tab or set up a new phone. It 409s
   * (`totp_already_enabled`) once a factor is in force, because replacing a
   * live secret is a disable then an enable and each step needs a code.
   */
  startTotp: (opts: CallOpts = {}) =>
    apiFetch<{ secret: string; provisioning_uri: string }>("/api/auth/totp/start", {
      method: "POST",
      ...opts,
    }).then(
      (dto): TotpEnrolment => ({ secret: dto.secret, provisioningUri: dto.provisioning_uri }),
    ),

  /** Turn it on, by proving a code from it. `totp_invalid`, or `totp_not_started`. */
  confirmTotp: (code: string, opts: CallOpts = {}) =>
    apiFetch<void>("/api/auth/totp/confirm", { method: "POST", body: { code }, ...opts }),

  /** Turn it off, which also needs a code: a stolen session must not be able
   *  to remove the protection that would have made it hard to steal. */
  disableTotp: (code: string, opts: CallOpts = {}) =>
    apiFetch<void>("/api/auth/totp/disable", { method: "POST", body: { code }, ...opts }),

  /** End every session this person has, on every device. */
  logoutEverywhere: (opts: CallOpts = {}) =>
    apiFetch<void>("/api/auth/logout-everywhere", { method: "POST", ...opts }),
};

// ---------------------------------------------------------------------------
// Skills (teardown P1)
// ---------------------------------------------------------------------------

interface SkillInfoDto {
  key: string;
  label: string;
  description: string;
  available: boolean;
  requires_integration: string | null;
  requires_config_key: string | null;
  needs: string | null;
}

export interface SkillInfo {
  key: string;
  label: string;
  description: string;
  available: boolean;
  requiresIntegration: string | null;
  requiresConfigKey: string | null;
  /** Plain-language reason it is not available yet. Null when it is. */
  needs: string | null;
}

export const skills = {
  list: (opts: CallOpts = {}) =>
    apiFetch<SkillInfoDto[]>("/api/config/skills", opts).then((rows): SkillInfo[] =>
      rows.map((r) => ({
        key: r.key,
        label: r.label,
        description: r.description,
        available: r.available,
        requiresIntegration: r.requires_integration,
        requiresConfigKey: r.requires_config_key,
        needs: r.needs,
      })),
    ),
};
