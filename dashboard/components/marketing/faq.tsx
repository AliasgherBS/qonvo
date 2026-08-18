import { Reveal, RevealGroup, RevealItem } from "@/components/marketing/reveal";
import { FAQ } from "@/lib/faq";

/**
 * A two-column list, not an accordion. Two reasons: accordions are a generic
 * pattern, and more importantly the answer text has to be in the DOM without
 * JavaScript for crawlers and LLMs to read it. This section is the citation
 * surface, and it is the source for the FAQPage JSON-LD.
 */
export function Faq() {
  return (
    <section className="border-t border-border/60">
      <div className="mx-auto w-full max-w-7xl px-4 py-24 sm:py-32">
        <Reveal>
          <h2 className="text-4xl font-extrabold leading-tight tracking-tight md:text-5xl">
            Questions, answered.
          </h2>
        </Reveal>

        <RevealGroup className="mt-14 grid gap-x-12 gap-y-9 md:grid-cols-2" stagger={0.05}>
          {FAQ.map(({ q, a }) => (
            <RevealItem key={q}>
              <h3 className="font-bold tracking-tight">{q}</h3>
              <p className="mt-2 leading-relaxed text-muted-foreground">{a}</p>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  );
}
