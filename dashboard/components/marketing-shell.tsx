import Link from "next/link";

import { auth } from "@/auth";
import { Logo } from "@/components/logo";
import { buttonClasses } from "@/components/ui/button";
import { LEGAL } from "@/lib/legal";

/**
 * The header's section anchors (teardown L3).
 *
 * Three and no more. The landing page is 7,600px tall, pricing sits 5,100px
 * down it and the FAQ 6,000px, and the header held nothing but the logo and
 * two account actions: a visitor who arrived wanting a price had no route to
 * one except the scroll wheel.
 *
 * The hrefs are root-relative rather than bare fragments because this header is
 * also the header of /terms and /privacy, where `#pricing` would scroll to
 * nothing. `/#pricing` navigates home first and then scrolls, from anywhere.
 * The ids themselves live on the sections in components/marketing/.
 */
const SECTIONS = [
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#pricing", label: "Pricing" },
  { href: "/#faq", label: "FAQ" },
];

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
            {/* Hidden below `sm`: at 375px the logo, three anchors and two
                buttons do not fit on one row, and a page this short on
                navigation has not earned a hamburger menu. */}
            <div className="mr-2 hidden items-center gap-1 sm:flex">
              {SECTIONS.map(({ href, label }) => (
                <Link
                  key={href}
                  href={href}
                  className="rounded-full px-3 py-2 text-sm font-semibold text-muted-foreground transition-colors hover:text-foreground"
                >
                  {label}
                </Link>
              ))}
            </div>
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
