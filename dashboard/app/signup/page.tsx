import Link from "next/link";

import { Logo } from "@/components/logo";
import { SignupForm } from "@/components/signup-form";

export default function SignupPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-sm space-y-8">
        <div className="space-y-2 text-center">
          <div className="flex justify-center">
            <Logo />
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight">Start your free trial</h1>
          <p className="text-sm text-muted-foreground">
            Put an AI rep on your WhatsApp. 14 days free, no card required.
          </p>
        </div>

        <SignupForm />

        <p className="text-center text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link href="/login" className="font-semibold text-primary-strong hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
