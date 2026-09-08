"use client";

import QRCode from "qrcode";
import { useEffect, useState } from "react";

/**
 * The QR an authenticator app scans, rendered from our own bundle.
 *
 * This was left out once with the reasoning that the CSP allows scripts from
 * four CDNs and none of them carries a QR library. That confused two different
 * things. The CSP restricts scripts *fetched at runtime from another origin*;
 * it says nothing about an npm dependency, which the build compiles into our
 * own JavaScript and serves from our own origin under `'self'`. `qrcode` is a
 * normal dependency, so this is a normal component.
 *
 * The alternative that shipped was a 32-character key typed by hand off a
 * screen. That is the thing nobody does, and an authenticator nobody sets up
 * protects nothing.
 *
 * Rendered as an SVG string rather than a canvas: it stays sharp on a phone
 * held up to a laptop, which is the actual scanning posture, and it needs no
 * ref-and-effect dance to exist before the paint.
 *
 * **Error correction level M**, not the library default L. A QR on a screen is
 * photographed at an angle, through glare, sometimes with a cracked lens. M
 * tolerates about 15% damage against L's 7% for a version bump that is
 * invisible at this size.
 *
 * The key stays visible beside this on purpose. A camera fails often enough
 * that "type it instead" has to be one glance away, not one support ticket.
 */
export function TotpQr({ uri, size = 176 }: { uri: string; size?: number }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    QRCode.toString(uri, {
      type: "svg",
      errorCorrectionLevel: "M",
      margin: 1,
      width: size,
      // Pure black on pure white, not the brand palette. A scanner needs
      // maximum luminance contrast, and Signal Green on Paper is a prettier
      // code that more phones fail to read. The frame around it carries the
      // brand instead, which is why this is the one place a raw hex is the
      // correct answer rather than a shortcut.
      //
      // brand-ok: no-raw-hex
      color: { dark: "#000000", light: "#ffffff" },
    })
      .then((out) => {
        if (live) setSvg(out);
      })
      .catch(() => {
        // Nothing to recover: the key and the deep link below both still work,
        // so a failed render costs the convenience and not the enrolment.
        if (live) setFailed(true);
      });
    return () => {
      live = false;
    };
  }, [uri, size]);

  if (failed) return null;

  return (
    <div
      className="inline-flex shrink-0 items-center justify-center rounded-2xl border border-border-strong bg-white p-2"
      style={{ width: size + 16, height: size + 16 }}
    >
      {svg ? (
        <div
          role="img"
          aria-label="QR code containing your two-factor setup key"
          // The SVG is produced by the QR library from a string we built
          // ourselves, so there is no untrusted input in it.
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      ) : (
        // A placeholder the same size, so the step does not jump as it appears.
        <div className="h-full w-full animate-pulse rounded-xl bg-surface-muted" />
      )}
    </div>
  );
}
