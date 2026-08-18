"use client";

import { signIn } from "next-auth/react";
import { useState, type FormEvent } from "react";

import { GoogleSignInButton } from "@/components/google-sign-in-button";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, auth } from "@/lib/api";

export function SignupForm() {
  const [businessName, setBusinessName] = useState("");
  const [ownerName, setOwnerName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);

    try {
      await auth.signup({ businessName, ownerName, email, password });
    } catch (err) {
      setLoading(false);
      setError(
        err instanceof ApiError && err.status === 409
          ? "An account with this email already exists. Try signing in instead."
          : "Couldn't create your account. Please try again.",
      );
      return;
    }

    // Auto sign-in, then straight to connecting a WhatsApp number.
    const result = await signIn("credentials", {
      email,
      password,
      redirect: false,
      callbackUrl: "/onboarding/connect",
    });
    setLoading(false);

    if (!result || result.error) {
      setError("Account created. Please sign in to continue.");
      return;
    }
    window.location.href = "/onboarding/connect";
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 rounded-2xl border border-border bg-surface p-6">
      <GoogleSignInButton label="Sign up with Google" />

      <div className="space-y-1.5">
        <Label htmlFor="business">Business name</Label>
        <Input
          id="business"
          required
          value={businessName}
          onChange={(e) => setBusinessName(e.target.value)}
          placeholder="Glow Salon"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="owner">Your name</Label>
        <Input
          id="owner"
          required
          value={ownerName}
          onChange={(e) => setOwnerName(e.target.value)}
          placeholder="Ali Raza"
        />
      </div>
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
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="At least 8 characters"
        />
      </div>

      {error ? (
        <p role="alert" className="rounded-xl bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      ) : null}

      <Button type="submit" disabled={loading} className="w-full">
        {loading ? "Creating your account…" : "Start free trial"}
      </Button>
    </form>
  );
}
