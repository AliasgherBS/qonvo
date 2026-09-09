import Link from "next/link";

import { Logo } from "@/components/logo";
import { buttonClasses } from "@/components/ui/button";

/**
 * The app's 404 (teardown A1).
 *
 * Before this existed, an unknown URL had two failure modes and both were bad.
 * Logged out, `/anything-mistyped` answered 307 to `/login?callbackUrl=...`,
 * so a stale marketing link asked a stranger to sign in and a crawler recorded
 * a soft 404. Logged in, it rendered Next's unstyled default: the words "404"
 * and "This page could not be found." on white, with no layout, no logo and no
 * way back. `middleware.ts` carries the other half of the fix, which is letting
 * an unmatched path reach this file at all.
 *
 * Three deliberate choices:
 *
 * It does not call `auth()`, so it does not know whether the visitor is signed
 * in. Next prerenders the `/_not-found` route, and reading cookies there is the
 * kind of thing that turns a 404 into a build error. Both routes out are
 * offered instead, and the inbox link resolves itself: middleware sends a
 * signed-out visitor from `/inbox` to `/login`, which is the correct
 * destination for them anyway.
 *
 * It follows the theme toggle rather than locking dark like the landing page.
 * That page is locked because the hero video's background is Ink; this one has
 * no video, and it is reached from inside the dashboard as often as from
 * outside, where a light-theme user would not expect a dark page.
 *
 * It does not apologise or blame. Most 404s here will be a typo or a link that
 * outlived a route, and the useful thing to say is which way is out.
 */
export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="border-b border-border">
        <div className="mx-auto flex w-full max-w-7xl items-center px-4 py-4">
          <Link href="/" aria-label="Qonvo home">
            <Logo />
          </Link>
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center px-4 py-20">
        <div className="w-full max-w-lg text-center">
          <p className="font-mono text-sm font-bold uppercase tracking-[0.2em] text-muted-foreground">
            404
          </p>

          <h1 className="mt-5 text-4xl font-extrabold leading-tight tracking-tight md:text-5xl">
            That page is not here.
          </h1>

          <p className="mx-auto mt-5 max-w-md text-lg leading-relaxed text-muted-foreground">
            The address may have a typo in it, or the link may be older than the
            page it pointed at. Nothing is broken.
          </p>

          <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <Link href="/" className={buttonClasses({ size: "lg" })}>
              Back to the home page
            </Link>
            <Link
              href="/inbox"
              className={buttonClasses({ variant: "outline", size: "lg" })}
            >
              Go to your inbox
            </Link>
          </div>
        </div>
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-center gap-4 px-4 py-6 text-sm text-muted-foreground">
          <Link href="/privacy" className="hover:text-foreground hover:underline">
            Privacy Policy
          </Link>
          <Link href="/terms" className="hover:text-foreground hover:underline">
            Terms of Service
          </Link>
        </div>
      </footer>
    </div>
  );
}
