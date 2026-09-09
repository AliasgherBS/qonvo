import { RevealGroup, RevealItem, Reveal } from "@/components/marketing/reveal";

/**
 * Statement left, its cost right. Deliberately not a mirrored image split, so
 * the layout family still changes immediately after the hero.
 *
 * It used to be a full-bleed statement with the costs stacked underneath at
 * `max-w-2xl`, which left 45 percent of a 1440px viewport empty and made this
 * the first of three sections in a row with the same silhouette (teardown L4).
 * The costs are the figures the section is missing, so they moved opposite the
 * statement rather than under it.
 *
 * The three items are costs, not features. Rows are separated by a single
 * hairline rather than boxed as cards, and carry no status dots: a ledger, not
 * a feature grid.
 */
const COSTS = [
  "Replied 7 hours later",
  "Booked with a competitor",
  "Never replied at all",
];

export function CostOfWaiting() {
  return (
    <section className="border-y border-border/60 bg-surface/40">
      <div className="mx-auto grid w-full max-w-7xl gap-12 px-4 py-24 sm:py-32 lg:grid-cols-[1.05fr_0.95fr] lg:items-center lg:gap-20">
        <div>
          <Reveal>
            <h2 className="text-4xl font-extrabold leading-tight tracking-tight md:text-5xl">
              It&apos;s 2 AM. A customer just messaged.
            </h2>
          </Reveal>

          <Reveal delay={0.08}>
            <p className="mt-5 max-w-xl text-lg text-muted-foreground">
              By morning, they have booked somewhere else.
            </p>
          </Reveal>
        </div>

        <RevealGroup className="border-t border-border/60" stagger={0.1}>
          {COSTS.map((cost, i) => (
            <RevealItem key={cost}>
              <p
                className={`py-6 text-xl font-semibold text-muted-foreground md:text-2xl ${
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
