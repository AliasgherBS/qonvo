"use client";

import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { Suspense, useEffect, useRef, useState } from "react";

import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { auth, describeError } from "@/lib/api";

/**
 * The landing page for the confirmation link (teardown X2).
 *
 * It confirms on mount rather than showing a button. The click already
 * happened, in the email; asking for a second one to confirm the first is
 * friction with nothing behind it.
 *
 * `/verify-email` is exempt from the middleware's credential-stripping, along
 * with `/reset-password` and `/accept-invite`. That exemption is load-bearing:
 * without it the middleware would redirect this URL to itself minus the token
 * before the page ever ran, and every confirmation link would appear to be
 * malformed. An earlier version of that middleware nearly shipped stripping
 * `token` unconditionally, which would have broken every password reset.
 */
function Verify() {
  const token = useSearchParams().get("token") ?? "";
  const router = useRouter();
  const { status } = useSession();
  const [state, setState] = useState<"working" | "done" | "failed">("working");
  const [error, setError] = useState<string | null>(null);
  // The link is single-use, so a double invocation would confirm on the first
  // call and then render the failure from the second. React's development
  // strict mode runs effects twice, which is exactly how that would happen.
  const started = useRef(false);

  useEffect(() => {
    if (!token || started.current) return;
    started.current = true;
    void (async () => {
      try {
        await auth.verifyEmail(token);
        setState("done");
      } catch (err) {
        setError(
          describeError(err, "This confirmation link is invalid, already used, or has expired."),
        );
        setState("failed");
      }
    })();
  }, [token]);

  // Signed in already, which is the usual case: signup logs you in, and the
  // link is opened in the same browser minutes later. Nothing more is needed,
  // so go where they were going.
  useEffect(() => {
    if (state === "done" && status === "authenticated") {
      const timer = setTimeout(() => router.replace("/inbox"), 1200);
      return () => clearTimeout(timer);
    }
  }, [state, status, router]);

  if (!token) {
    return (
      <Card>
        <XCircle className="mx-auto h-8 w-8 text-danger" />
        <p className="text-sm">
          This confirmation link is missing its token. Sign in and use the banner at the top of
          the page to send yourself a new one.
        </p>
        <Link href="/login" className="text-sm font-semibold text-primary-strong hover:underline">
          Go to sign in
        </Link>
      </Card>
    );
  }

  if (state === "working") {
    return (
      <Card>
        <Loader2 className="mx-auto h-8 w-8 animate-spin text-muted-foreground" />
        <p className="text-sm text-muted-foreground">Confirming your address…</p>
      </Card>
    );
  }

  if (state === "failed") {
    return (
      <Card>
        <XCircle className="mx-auto h-8 w-8 text-danger" />
        <p className="text-sm">{error}</p>
        <p className="text-xs text-muted-foreground">
          If you have already confirmed this address, you are all set and can simply sign in.
          Otherwise sign in and use the banner at the top of the page to send a new link.
        </p>
        <Link href="/login" className="text-sm font-semibold text-primary-strong hover:underline">
          Go to sign in
        </Link>
      </Card>
    );
  }

  return (
    <Card>
      <CheckCircle2 className="mx-auto h-8 w-8 text-primary-strong" />
      <p className="text-sm font-bold">Your email address is confirmed</p>
      <p className="text-sm text-muted-foreground">
        You can now connect your WhatsApp number and let your rep start answering.
      </p>
      {status === "authenticated" ? (
        <p className="text-xs text-muted-foreground">Taking you back to Qonvo…</p>
      ) : (
        <Button className="w-full" onClick={() => router.push("/login")}>
          Sign in
        </Button>
      )}
    </Card>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="space-y-4 rounded-2xl border border-border bg-surface p-6 text-center">
      {children}
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-sm space-y-8">
        <div className="space-y-2 text-center">
          <div className="flex justify-center">
            <Logo />
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight">Confirm your email</h1>
        </div>
        <Suspense fallback={null}>
          <Verify />
        </Suspense>
      </div>
    </main>
  );
}
