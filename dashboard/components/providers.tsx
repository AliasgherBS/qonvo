"use client";

import type { Session } from "next-auth";
import { SessionProvider } from "next-auth/react";
import type { ReactNode } from "react";

import { ToastProvider } from "@/components/ui/toast";

export function Providers({ children, session }: { children: ReactNode; session: Session | null }) {
  return (
    // Seed the provider with the server-resolved session so `useSession()` (and
    // therefore `useAuthToken()`) is populated on the very first client render.
    // Without this, a fresh page load fetches protected data before the session
    // hydrates → the request goes out token-less → backend 401 → signOut() →
    // redirect to /login. That was the login "redirect loop".
    <SessionProvider session={session}>
      <ToastProvider>{children}</ToastProvider>
    </SessionProvider>
  );
}
