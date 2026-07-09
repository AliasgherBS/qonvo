import { Suspense } from "react";

import { Logo } from "@/components/logo";
import { LoginForm } from "@/components/login-form";

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-sm space-y-8">
        <div className="space-y-2 text-center">
          <div className="flex justify-center">
            <Logo />
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight">Welcome back</h1>
          <p className="text-sm text-muted-foreground">
            Never miss a customer — sign in to your Qonvo dashboard.
          </p>
        </div>

        <Suspense fallback={null}>
          <LoginForm />
        </Suspense>

        <p className="text-center text-xs text-muted-foreground">
          Accounts are provisioned by your Qonvo team. Ask your admin for an invite.
        </p>
      </div>
    </main>
  );
}
