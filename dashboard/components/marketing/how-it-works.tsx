import { Reveal, RevealGroup, RevealItem } from "@/components/marketing/reveal";

/**
 * No "Step 1 / Step 2 / Step 3" labels: the step content is the label. The
 * numeral is a visual marker, not a word.
 *
 * Vertical staggered rows with a connecting rule, rather than three equal
 * cards. Pinning three short steps would cost scroll length for no gain, so
 * this is not a sticky stack.
 */
const STEPS = [
  {
    title: "Connect WhatsApp",
    body: "Scan one QR code with the number you already give customers.",
  },
  {
    title: "Teach it your business",
    body: "Paste in your hours, prices and the questions you answer most days.",
  },
  {
    title: "Let it answer",
    body: "Send it a test message, then let it work while you get on with the job.",
  },
];

export function HowItWorks() {
  return (
    <section className="border-t border-border/60">
      <div className="mx-auto w-full max-w-7xl px-4 py-24 sm:py-32">
        <Reveal>
          <h2 className="text-4xl font-extrabold leading-tight tracking-tight md:text-5xl">
            Live in a day. <span className="text-primary">No code.</span>
          </h2>
        </Reveal>

        <RevealGroup className="mt-14 max-w-3xl" stagger={0.12}>
          {STEPS.map(({ title, body }, i) => (
            <RevealItem key={title}>
              <div className="flex gap-7 pb-14 last:pb-0">
                <div className="flex flex-col items-center">
                  <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-primary/40 font-mono text-sm font-bold text-primary">
                    {i + 1}
                  </span>
                  {i < STEPS.length - 1 ? (
                    <span className="mt-3 w-px flex-1 bg-border" aria-hidden="true" />
                  ) : null}
                </div>
                <div className="pt-2">
                  <h3 className="text-2xl font-bold tracking-tight">{title}</h3>
                  <p className="mt-2.5 max-w-lg text-lg text-muted-foreground">{body}</p>
                </div>
              </div>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  );
}
