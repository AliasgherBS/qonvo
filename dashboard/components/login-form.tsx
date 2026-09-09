"use client";

import { signIn } from "next-auth/react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { GoogleSignInButton } from "@/components/google-sign-in-button";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * Why a Google sign-in was refused, in words the person can act on.
 *
 * `password_account_unverified` is the pre-hijacking guard (teardown X2): an
 * account with this address exists, was created with a password, and has never
 * confirmed the address, so signing into it on Google's word alone could hand
 * over a workspace somebody else created. Without a message here the user
 * clicks Google and simply arrives back at this page, which is
 * indistinguishable from a bug.
 */
const TOTP_ERRORS: Record<string, string> = {
  totp_required: "",
  totp_invalid: "That code is not right, or it has expired. Try the next one your app shows.",
  totp_replayed: "That code has already been used. Wait for your app to show the next one.",
};

const SIGN_IN_ERRORS: Record<string, string> = {
  password_account_unverified:
    "An account with this email already exists and uses a password. Sign in with that " +
    "password below. If you have forgotten it, reset it and that will confirm your " +
    "address at the same time.",
  google_exchange: "We could not complete your Google sign-in. Try again, or use your password.",
};

export function LoginForm() {
  const searchParams = useSearchParams();
  const callbackUrl = searchParams.get("callbackUrl") ?? "/inbox";
  const refusal = searchParams.get("error");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  // Revealed only once the API has said a code is needed, so the form never
  // has to know in advance which addresses have 2FA. Asking everybody would
  // be confusing; asking only enrolled addresses would tell an attacker which
  // ones those are.
  const [needsCode, setNeedsCode] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(
    refusal ? (SIGN_IN_ERRORS[refusal] ?? SIGN_IN_ERRORS.google_exchange) : null,
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);

    const result = await signIn("credentials", {
      email,
      password,
      totpCode,
      redirect: false,
      callbackUrl,
    });

    setLoading(false);

    if (!result || result.error) {
      // A second factor is not a failed password. Collapsing the two was a
      // lockout: an account with 2FA enabled could not sign in at all, and the
      // form blamed a password that was correct.
      const code = (result as { code?: string } | undefined)?.code;
      if (code === "totp_required" || code === "totp_invalid" || code === "totp_replayed") {
        setNeedsCode(true);
        setTotpCode("");
        setError(TOTP_ERRORS[code]);
        return;
      }
      setError("Couldn't sign you in. Check your email and password and try again.");
      return;
    }

    window.location.href = callbackUrl;
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 rounded-2xl border border-border bg-surface p-6">
      <GoogleSignInButton callbackUrl={callbackUrl} label="Sign in with Google" />

      <div className="space-y-1.5">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@business.com"
        />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label htmlFor="password">Password</Label>
          <Link href="/forgot-password" className="text-xs font-semibold text-primary-strong hover:underline">
            Forgot password?
          </Link>
        </div>
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••"
        />
      </div>

      {needsCode ? (
        <div className="space-y-1.5">
          <Label htmlFor="totp-code">Authentication code</Label>
          <Input
            id="totp-code"
            // `text` with a numeric mode, not `type="number"`: a number input
            // strips a leading zero, and a fifth of all valid codes start with
            // one.
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]*"
            maxLength={6}
            required
            autoFocus
            value={totpCode}
            onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ""))}
            placeholder="123456"
          />
          <p className="text-xs text-muted-foreground">
            The six digits from your authenticator app.
          </p>
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="rounded-xl bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      ) : null}

      <Button type="submit" disabled={loading} className="w-full">
        {loading ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
