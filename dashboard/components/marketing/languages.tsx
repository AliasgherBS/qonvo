import { Marquee, Reveal } from "@/components/marketing/reveal";

/**
 * The page's only marquee, and its one deliberate light block. The promo video
 * makes the same switch at this beat, so it is a colour-block story rather
 * than an accidental theme flip.
 *
 * Each pill carries `lang` so screen readers switch pronunciation. The
 * non-Latin strings are why the font stack names Noto Sans Arabic and Noto
 * Sans Devanagari: Manrope has no glyphs for them.
 */
const GREETINGS = [
  { text: "Hello", lang: "en" },
  { text: "مرحبا", lang: "ar" },
  { text: "السلام علیکم", lang: "ur" },
  { text: "Hola", lang: "es" },
  { text: "नमस्ते", lang: "hi" },
  { text: "Bonjour", lang: "fr" },
  { text: "Olá", lang: "pt" },
  { text: "Merhaba", lang: "tr" },
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
              key={lang}
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
