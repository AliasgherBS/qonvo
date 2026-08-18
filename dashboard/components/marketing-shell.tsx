import Link from "next/link";

import { auth } from "@/auth";
import { Logo } from "@/components/logo";
import { buttonClasses } from "@/components/ui/button";
import { LEGAL } from "@/lib/legal";

/**
 * Header + footer for the public pages (home, terms, privacy).
 *
 * The footer links Terms and Privacy from every public page on purpose: Google's
 * OAuth verification requires the privacy policy to be reachable from the
 * homepage and served on the same domain as the app.
 */
export async function MarketingShell({ children }: { children: React.ReactNode }) {
  const session = await auth();
  const signedIn = Boolean(session?.accessToken);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="border-b border-border">
        <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-4 py-4">
          <Link href="/" aria-label="Qonvo home">
            <Logo />
          </Link>
          <nav className="flex items-center gap-2">
            {signedIn ? (
              <Link href="/inbox" className={buttonClasses({ size: "sm" })}>
                Go to dashboard
              </Link>
            ) : (
              <>
                <Link href="/login" className={buttonClasses({ variant: "ghost", size: "sm" })}>
                  Sign in
                </Link>
                <Link href="/signup" className={buttonClasses({ size: "sm" })}>
                  Start free trial
                </Link>
              </>
            )}
          </nav>
        </div>
      </header>

      <main className="flex-1">{children}</main>

      <footer className="border-t border-border">
        <div className="mx-auto flex w-full max-w-7xl flex-col gap-3 px-4 py-6 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <p>
            © {new Date().getFullYear()} {LEGAL.companyName}
          </p>
          <nav className="flex flex-wrap items-center gap-4">
            <Link href="/privacy" className="hover:text-foreground hover:underline">
              Privacy Policy
            </Link>
            <Link href="/terms" className="hover:text-foreground hover:underline">
              Terms of Service
            </Link>
            <a
              href={`mailto:${LEGAL.contactEmail}`}
              className="hover:text-foreground hover:underline"
            >
              Contact
            </a>
          </nav>
        </div>
      </footer>
    </div>
  );
}

/** Shared page frame for the two legal documents. */
export function LegalPage({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-12">
      <h1 className="text-3xl font-extrabold tracking-tight">{title}</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Last updated {LEGAL.lastUpdated}
      </p>
      <div className="mt-8 space-y-8 text-sm leading-relaxed">{children}</div>
    </div>
  );
}

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-bold tracking-tight">{title}</h2>
      <div className="space-y-3 text-muted-foreground">{children}</div>
    </section>
  );
}
