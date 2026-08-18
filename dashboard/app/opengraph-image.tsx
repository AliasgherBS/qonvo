import { ImageResponse } from "next/og";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { SITE } from "@/lib/site";

export const alt = `${SITE.name}: ${SITE.tagline}`;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/**
 * Social card, rendered at build time with the real brand mark and palette.
 *
 * Satori (which powers ImageResponse) cannot use next/font variables, so the
 * mark is inlined as a data URI from public/ and the type falls back to the
 * system sans. That is a deliberate trade: a correct mark and correct colours
 * matter far more on a 1200x630 card than the exact display face.
 */
export default async function Image() {
  const mark = await readFile(join(process.cwd(), "public/logo-mark.png"));
  const markSrc = `data:image/png;base64,${mark.toString("base64")}`;

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "0 90px",
          background: "#08130E",
        }}
      >
        <img src={markSrc} width={104} height={104} alt="" />
        <div
          style={{
            marginTop: 40,
            fontSize: 82,
            fontWeight: 800,
            letterSpacing: "-0.03em",
            lineHeight: 1.05,
            color: "#F3EFE6",
            display: "flex",
          }}
        >
          Never miss a customer
          <span style={{ color: "#00C776" }}>&nbsp;again.</span>
        </div>
        <div
          style={{
            marginTop: 28,
            fontSize: 32,
            color: "#F3EFE6",
            opacity: 0.66,
            display: "flex",
          }}
        >
          An AI customer rep on your WhatsApp. Answers, books, follows up.
        </div>
      </div>
    ),
    size,
  );
}
