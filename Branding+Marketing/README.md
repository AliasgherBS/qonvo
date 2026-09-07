# Branding and marketing

| What | Where | In git |
|---|---|---|
| Brand kit (the source of the five colours and two faces) | `Qonvo Brand Kit.pdf` | no |
| Logo, four sizes plus an ink variant | `logo/` | **yes** |
| Marketing kit: promo, decks and brand kit on one page | `qonvo-marketing-kit.html` / `.pdf` | no |
| Three pitch decks, HTML and 16:9 PDF, plus their builder | `pitch-decks/` | no |
| Promo film, poster frame and its Remotion project | `promo-video/` | no |
| The earlier promo | `Qonvo Promo Video.mp4` | no |

**Most of this directory is deliberately not version controlled**, so a fresh
clone will find the table above mostly describing files that are not there. Git
keeps every revision of a binary forever and cannot diff them, and the brand kit
PDF plus the promo video alone were 15 MB of a 26 MB repository. They live on
disk and in whatever backup the rest of your work lives in; carry them across
out of band.

The logos are the exception, at 112 KB total: `pitch-decks/src/hub.mjs` reads
them, so a clone without them cannot rebuild a deck. The dashboard does not use
these files. It carries its own optimised copies under `dashboard/public/`.

Everything here is built from the tokens in
[`dashboard/app/globals.css`](../dashboard/app/globals.css), which are themselves
lifted from the brand kit PDF: Signal Green `#00C776`, Volt `#C6FF3D`, Deep Forest
`#0B3B2B`, Ink `#08130E`, Paper `#F3EFE6`, set in Bricolage Grotesque and Manrope
with Geist Mono for figures.

Three house rules carry across all of it, and the deck build enforces the first and
last automatically:

- **No em dash and no en dash** in any copy, matching gate two of
  [`dashboard/scripts/verify-brand.mjs`](../dashboard/scripts/verify-brand.mjs).
- **Volt once per piece.** The brand kit calls it a spotlight, not a background.
- **The five colours are exact.** Nothing introduces a sixth.

See the README in each folder for how to rebuild.
