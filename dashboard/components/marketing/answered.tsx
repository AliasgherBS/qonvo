import { Reveal } from "@/components/marketing/reveal";

/**
 * Split, mirrored from the hero: visual left, copy right. Two splits total on
 * the page and they are not adjacent, so the zigzag cap is respected.
 *
 * The visual used to be `/conversation.png`, a still of the same dental
 * booking chat the hero video plays 1,600px further up: same business, same
 * messages, same voice note (teardown L5). One asset shown twice reads as a
 * page with one asset, and it spent the strongest slot below the fold on
 * repetition.
 *
 * So this shows the half the hero never does. A different business, and the
 * day Qonvo wrote into rather than the chat it answered. It is also the only
 * picture on the page of the claim beside it, "checks when you are genuinely
 * free": the two Busy blocks are the owner's real commitments, which is what
 * the `calendar.freebusy` scope buys and what stops the rep double-booking
 * somebody. Drawn from brand tokens rather than exported as an image, so it
 * stays sharp at any size, costs no bytes, and can be read out.
 *
 * `role="img"` plus a label: the rows are real text, but a screen reader
 * announcing eight disconnected fragments describes a table, not a picture.
 */
const DAY = [
  { time: "10:00", label: "Busy", tone: "busy" },
  { time: "11:30", label: "Fade and beard trim", tone: "booked" },
  { time: "1:00", label: "Busy", tone: "busy" },
  { time: "3:00", label: "Open", tone: "open" },
] as const;

const TONE = {
  busy: "border-border/60 bg-surface-muted/40 text-muted-foreground",
  booked: "border-primary/50 bg-primary/12 text-foreground",
  open: "border-dashed border-border/60 text-muted-foreground",
} as const;

function CalendarDay() {
  return (
    <div
      role="img"
      aria-label="A Tuesday in the barber's calendar. Ten o'clock and one o'clock are already busy, so Qonvo offered half past eleven and booked a fade and beard trim into it. Three o'clock is still open."
      className="w-full max-w-[380px] rounded-[2rem] border border-border/60 bg-surface p-6 shadow-xl sm:p-7"
    >
      <div className="flex items-baseline justify-between">
        <p className="text-lg font-bold tracking-tight">Tuesday</p>
        <p className="font-mono text-xs uppercase tracking-[0.18em] text-muted-foreground">
          Your calendar
        </p>
      </div>

      <div className="mt-6 space-y-2.5">
        {DAY.map(({ time, label, tone }) => (
          <div key={time} className="flex items-center gap-3">
            <span className="w-14 shrink-0 font-mono text-xs text-muted-foreground">
              {time}
            </span>
            <div
              className={`flex flex-1 items-center justify-between gap-3 rounded-2xl border px-4 py-3.5 ${TONE[tone]}`}
            >
              <span className="text-sm font-semibold">{label}</span>
              {tone === "booked" ? (
                <span className="shrink-0 rounded-full bg-primary/20 px-2.5 py-1 font-mono text-[0.625rem] font-bold uppercase tracking-[0.12em] text-primary">
                  Qonvo
                </span>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Answered() {
  return (
    <section className="mx-auto grid w-full max-w-7xl items-center gap-12 px-4 py-24 sm:py-32 lg:grid-cols-2">
      <Reveal className="order-2 flex justify-center lg:order-1 lg:justify-start">
        <CalendarDay />
      </Reveal>

      <div className="order-1 lg:order-2">
        <Reveal>
          <h2 className="text-4xl font-extrabold leading-tight tracking-tight md:text-5xl">
            Answered in seconds.
            <br />
            Booked <span className="text-primary">automatically.</span>
          </h2>
        </Reveal>
        <Reveal delay={0.1}>
          <p className="mt-6 max-w-lg text-lg leading-relaxed text-muted-foreground">
            Qonvo reads the question, checks when you are genuinely free, offers
            the open slots and confirms the booking. Your customer installs
            nothing.
          </p>
        </Reveal>
      </div>
    </section>
  );
}
