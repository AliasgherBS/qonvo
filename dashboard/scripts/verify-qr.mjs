#!/usr/bin/env node
/**
 * Prove the two-factor QR encodes what it claims, by decoding it.
 *
 * The reason a QR was left out of the enrolment flow at first was a fair one:
 * an encoder nobody can test against a real camera is a QR that might scan
 * wrong, and a wrong QR fails at the exact moment somebody is locked out of
 * their account. This is the test that objection was asking for.
 *
 * It encodes with the same options the component uses, rasterises at the size
 * the component renders, and decodes the pixels with a *different* library.
 * Both agreeing on the payload is the only evidence that means anything here;
 * a QR that renders is not a QR that scans.
 *
 * Run: npm run verify:qr
 */
import QRCode from "qrcode";
import jsQR from "jsqr";
import { PNG } from "pngjs";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Must stay in step with components/account/totp-qr.tsx.
const OPTIONS = {
  errorCorrectionLevel: "M",
  margin: 1,
  width: 176,
  color: { dark: "#000000", light: "#ffffff" }, // brand-ok: no-raw-hex
};

// The shapes backend/app/core/totp.py actually produces, including the two
// that have broken QR parsing in real apps before: a percent-encoded colon in
// the label, and a plus in the local part of an address.
const CASES = [
  "otpauth://totp/Qonvo%3Aadmin%40qonvo.org?secret=OXIX5YIXUR7JZKLFKG6NWMIWGWKTTUVQ&issuer=Qonvo&algorithm=SHA1&digits=6&period=30",
  "otpauth://totp/Qonvo%3Aowner%2Btag%40theclinic.pk?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=Qonvo&algorithm=SHA1&digits=6&period=30",
  "otpauth://totp/Qonvo%3Aa%20b%40qonvo.org?secret=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA&issuer=Qonvo&algorithm=SHA1&digits=6&period=30",
];

const dir = mkdtempSync(join(tmpdir(), "qonvo-qr-"));
let failures = 0;

for (const [i, uri] of CASES.entries()) {
  const file = join(dir, `qr-${i}.png`);
  await QRCode.toFile(file, uri, OPTIONS);
  const png = PNG.sync.read(readFileSync(file));
  const decoded = jsQR(new Uint8ClampedArray(png.data), png.width, png.height);

  if (!decoded) {
    console.error(`verify-qr: case ${i} produced an image no decoder could read`);
    failures++;
  } else if (decoded.data !== uri) {
    console.error(`verify-qr: case ${i} round-tripped to a different payload`);
    console.error(`  encoded: ${uri}`);
    console.error(`  decoded: ${decoded.data}`);
    failures++;
  }
}

rmSync(dir, { recursive: true, force: true });

if (failures > 0) {
  console.error(`\nverify-qr: ${failures} failure(s)`);
  process.exit(1);
}
console.log(`verify-qr: ${CASES.length} provisioning URIs encode and decode identically`);
