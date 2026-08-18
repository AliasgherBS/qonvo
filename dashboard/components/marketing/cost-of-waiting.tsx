import { RevealGroup, RevealItem, Reveal } from "@/components/marketing/reveal";

/**
 * Full-bleed statement. Deliberately not a split, so the layout family changes
 * immediately after the hero.
 *
 * The three items are costs, not features. Rows are separated by a single
 * hairline rather than boxed as cards, and carry no status dots.
 */
const COSTS = [
  "Replied 7 hours later",
  "Booked with a competitor",
  "Never replied at all",
];

export function CostOfWaiting() {
  return (
    <section className="border-y border-border/60 bg-surface/40">
      <div className="mx-auto w-full max-w-7xl px-4 py-24 sm:py-32">
        <Reveal>
          <h2 className="max-w-3xl text-4xl font-extrabold leading-tight tracking-tight md:text-5xl">
            It&apos;s 2 AM. A customer just messaged.
          </h2>
        </Reveal>

        <Reveal delay={0.08}>
          <p className="mt-5 max-w-xl text-lg text-muted-foreground">
            By morning, they have booked somewhere else.
          </p>
        </Reveal>

        <RevealGroup className="mt-14 max-w-2xl" stagger={0.1}>
          {COSTS.map((cost, i) => (
            <RevealItem key={cost}>
              <p
                className={`py-5 text-xl font-semibold text-muted-foreground md:text-2xl ${
                  i > 0 ? "border-t border-border/60" : ""
                }`}
              >
                {cost}
              </p>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  );
}
