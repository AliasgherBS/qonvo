import { Reveal } from "@/components/marketing/reveal";

/**
 * Full-width section, its own layout family.
 *
 * The waveform is decoration built from a fixed array, not random values, so
 * it is stable across renders. Deliberately no play button: a control that
 * does nothing is worse than no control, and there is no audio file to play.
 */
const BARS = [
  18, 34, 52, 30, 66, 44, 78, 40, 58, 26, 70, 48, 36, 62, 22, 54, 38, 68, 30, 46,
];

export function Voice() {
  return (
    <section className="border-t border-border/60 bg-surface/40">
      <div className="mx-auto w-full max-w-4xl px-4 py-24 text-center sm:py-32">
        <Reveal>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-primary">
            Voice, not just text
          </p>
        </Reveal>

        <Reveal delay={0.08}>
          <h2 className="mt-4 text-4xl font-extrabold leading-tight tracking-tight md:text-5xl">
            Send a voice note. Get one back.
          </h2>
        </Reveal>

        <Reveal delay={0.16}>
          <div
            className="mx-auto mt-12 flex h-20 max-w-md items-center justify-center gap-1.5"
            aria-hidden="true"
          >
            {BARS.map((h, i) => (
              <span
                key={i}
                className="w-1.5 rounded-full bg-primary/70"
                style={{ height: `${h}%` }}
              />
            ))}
          </div>
        </Reveal>

        <Reveal delay={0.22}>
          <p className="mx-auto mt-10 max-w-xl text-lg leading-relaxed text-muted-foreground">
            Qonvo understands voice messages and replies with one, in the same
            language your customer spoke.
          </p>
        </Reveal>
      </div>
    </section>
  );
}
