import { Reveal } from "@/components/marketing/reveal";
import { VoicePlayer } from "@/components/marketing/voice-player";

/**
 * Full-width section, its own layout family.
 *
 * The waveform used to be decoration with deliberately nothing to press,
 * because there was no audio file: the strongest claim on the page was the one
 * piece of it a visitor could not check (teardown L7). There is a clip now, and
 * the bars are its progress and its seek bar.
 */

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
          <VoicePlayer />
          <p className="mx-auto mt-4 max-w-md text-sm text-muted-foreground">
            A real reply from a Qonvo rep, answering a question and offering a time.
          </p>
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
