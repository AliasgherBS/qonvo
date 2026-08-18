"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";

import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { describeError, team } from "@/lib/api";

interface Preview {
  valid: boolean;
  email: string | null;
  role: string | null;
  business_name: string | null;
  needs_password: boolean;
  reason: string | null;
}

function AcceptInviteForm() {
  const token = useSearchParams().get("token") ?? "";
  const [preview, setPreview] = useState<Preview | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(true);
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setLoadingPreview(false);
      return;
    }
    team
      .previewInvite(token)
      .then((p) => setPreview(p))
      .catch(() => setPreview({ valid: false, email: null, role: null, business_name: null, needs_password: false, reason: "This invitation could not be loaded." }))
      .finally(() => setLoadingPreview(false));
  }, [token]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await team.acceptInvite({
        token,
        ...(preview?.needs_password ? { password, full_name: fullName } : {}),
      });
      setDone(true);
    } catch (err) {
      setError(describeError(err, "Couldn't accept this invitation. It may have expired."));
    } finally {
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <p className="rounded-2xl border border-border bg-surface p-6 text-center text-sm text-danger">
        This invite link is missing its token.
      </p>
    );
  }

  if (loadingPreview) {
    return <p className="rounded-2xl border border-border bg-surface p-6 text-center text-sm text-muted-foreground">Loading…</p>;
  }

  if (!preview?.valid) {
    return (
      <p className="rounded-2xl border border-border bg-surface p-6 text-center text-sm text-danger">
        {preview?.reason ?? "This invitation is invalid, used, or expired."}
      </p>
    );
  }

  if (done) {
    return (
      <div className="space-y-4 rounded-2xl border border-border bg-surface p-6 text-center">
        <p className="text-sm">
          You&apos;ve joined <span className="font-semibold">{preview.business_name}</span>. Sign in
          with your email to get started.
        </p>
        <Link href="/login" className="text-sm font-semibold text-primary-strong hover:underline">
          Go to sign in
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 rounded-2xl border border-border bg-surface p-6">
      <p className="text-sm text-muted-foreground">
        You&apos;ve been invited to join <span className="font-semibold text-foreground">{preview.business_name}</span>{" "}
        as <span className="font-semibold text-foreground">{preview.role}</span> ({preview.email}).
      </p>
      {preview.needs_password ? (
        <>
          <div className="space-y-1.5">
            <Label htmlFor="full-name">Your name</Label>
            <Input id="full-name" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Jane Doe" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Choose a password</Label>
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
        </>
      ) : (
        <p className="rounded-xl bg-surface-muted px-3 py-2 text-xs text-muted-foreground">
          You already have a Qonvo account. Accepting adds this workspace to it.
        </p>
      )}
      {error ? (
        <p role="alert" className="rounded-xl bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      ) : null}
      <Button type="submit" disabled={submitting} className="w-full">
        {submitting ? "Joining…" : "Accept invitation"}
      </Button>
    </form>
  );
}

export default function AcceptInvitePage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-sm space-y-8">
        <div className="space-y-2 text-center">
          <div className="flex justify-center">
            <Logo />
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight">Join your team</h1>
        </div>
        <Suspense fallback={null}>
          <AcceptInviteForm />
        </Suspense>
      </div>
    </main>
  );
}
