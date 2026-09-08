import { Marquee, Reveal } from "@/components/marketing/reveal";

/**
 * The page's only marquee, and its one deliberate light block. The promo video
 * makes the same switch at this beat, so it is a colour-block story rather
 * than an accidental theme flip.
 *
 * Each pill carries `lang` so screen readers switch pronunciation. The
 * non-Latin strings are why the font stack names Noto Sans Arabic and Noto
 * Sans Devanagari: Manrope has no glyphs for them. Nothing here is in a script
 * those two do not cover, which is deliberate. A Cyrillic or CJK greeting
 * would need a third face loaded or it renders as tofu boxes, and a tofu box
 * is a worse advert for speaking a customer's language than not listing it.
 *
 * Fourteen entries, not eight (teardown L6). Eight pills were narrower than a
 * desktop viewport, so Bonjour, Olá and Merhaba each appeared twice on one
 * screen and the loop read as a rendering bug rather than as motion. The strip
 * has to be wider than the widest viewport for the seam to stay off screen.
 * The list also leads with the market it is sold into: Urdu, Roman Urdu,
 * Punjabi, Pashto and Sindhi before the international ones.
 *
 * Keyed on the text, not the language: Urdu appears twice, once in its own
 * script and once in the Latin transliteration people actually type on
 * WhatsApp, and two pills keyed `ur` would collide.
 */
const GREETINGS = [
  { text: "Hello", lang: "en" },
  { text: "السلام علیکم", lang: "ur" },
  { text: "Assalam o alaikum", lang: "ur-Latn" },
  { text: "کی حال اے", lang: "pa-Arab" },
  { text: "ستړی مه شې", lang: "ps" },
  { text: "ڪيئن آهيو", lang: "sd" },
  { text: "مرحبا", lang: "ar" },
  { text: "नमस्ते", lang: "hi" },
  { text: "Hola", lang: "es" },
  { text: "Bonjour", lang: "fr" },
  { text: "Olá", lang: "pt" },
  { text: "Merhaba", lang: "tr" },
  { text: "Ciao", lang: "it" },
  { text: "Hallo", lang: "de" },
];

export function Languages() {
  return (
    <section className="bg-brand-paper py-24 text-brand-surface-900 sm:py-32">
      <div className="mx-auto w-full max-w-7xl px-4 text-center">
        <Reveal>
          <h2 className="text-4xl font-extrabold leading-tight tracking-tight md:text-5xl">
            Speaks every customer&apos;s language.
          </h2>
        </Reveal>
      </div>

      <Reveal delay={0.1} className="mt-12">
        <Marquee>
          {GREETINGS.map(({ text, lang }) => (
            <span
              key={text}
              lang={lang}
              className="rounded-full bg-brand-surface-900 px-7 py-3 text-xl font-bold text-brand-paper"
            >
              {text}
            </span>
          ))}
        </Marquee>
      </Reveal>

      <div className="mx-auto mt-12 w-full max-w-7xl px-4 text-center">
        <Reveal delay={0.16}>
          <p className="mx-auto max-w-xl text-lg text-brand-surface-700">
            It detects the language and replies in it, by text or by voice.
          </p>
        </Reveal>
      </div>
    </section>
  );
}
