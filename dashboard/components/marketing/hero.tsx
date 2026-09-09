import Link from "next/link";

import { Reveal } from "@/components/marketing/reveal";
import { buttonClasses } from "@/components/ui/button";

/**
 * Four text elements is the cap and this uses all four: headline, subtext, two
 * CTAs. No eyebrow, no trust strip, no tagline under the buttons. Top padding
 * stays at pt-24 so the content does not float down the viewport.
 *
 * The video is the brand's own promo, cut to the booking sequence. Its
 * background is Ink, which is why the whole page is locked dark: on Paper it
 * would read as a pasted-in rectangle.
 */
export function Hero() {
  return (
    <section className="mx-auto grid w-full max-w-7xl items-center gap-12 px-4 pt-16 pb-20 sm:pt-24 lg:grid-cols-11 lg:gap-8">
      <div className="lg:col-span-6">
        <Reveal>
          <h1 className="text-5xl font-extrabold leading-[1.05] tracking-tight md:text-6xl lg:text-7xl">
            Never miss a<br />
            customer <span className="text-primary">again.</span>
          </h1>
        </Reveal>

        <Reveal delay={0.1}>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted-foreground">
            Qonvo answers on your WhatsApp number in seconds, day or night, then
            books the slot and logs the lead.
          </p>
        </Reveal>

        <Reveal delay={0.18}>
          <div className="mt-9 flex flex-wrap items-center gap-3">
            <Link href="/signup" className={buttonClasses({ size: "lg" })}>
              Start free trial
            </Link>
            <Link
              href="/login"
              className={buttonClasses({ variant: "outline", size: "lg" })}
            >
              Sign in
            </Link>
          </div>
        </Reveal>
      </div>

      <div className="lg:col-span-5">
        <Reveal delay={0.24} className="flex justify-center lg:justify-end">
          {/*
            muted + playsInline are both required or mobile Safari refuses to
            autoplay and the hero shows a black box.

            The poster is the frame at 7.0s of a 12.5s loop: the question, two
            offered slots, the customer's choice, a voice note mid-play and the
            booking confirmed. It used to be the video's own first frame, which
            is a nearly empty chat window. That bought a seamless handoff into
            playback and paid for it with the one image every visitor sees
            first, every reduced-motion visitor only ever sees, and every
            connection too slow to autoplay is left with. The argument for the
            product is in this frame and not in that one.

            The handoff cost is smaller than it looks: the loop already cuts
            from the finished conversation back to the empty one every 12.5
            seconds, so poster to first frame is a cut the visitor sees on
            every lap anyway.

            WebP at quality 0.8, 30 KB against 59 KB for the same frame as
            JPEG. Extracted with headless Chromium (canvas drawImage on the
            webm, then toDataURL) because this box has no ffmpeg.
          */}
          <video
            className="w-full max-w-[380px] rounded-[2rem] shadow-xl motion-reduce:hidden"
            autoPlay
            muted
            loop
            playsInline
            preload="metadata"
            poster="/hero-poster.webp"
            aria-label="A customer asks to book a cleaning. Qonvo offers two open slots, takes a voice note, and confirms the three o'clock booking."
          >
            <source src="/hero.webm" type="video/webm" />
            <source src="/hero.mp4" type="video/mp4" />
          </video>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/hero-poster.webp"
            alt="A WhatsApp chat in which Qonvo answers a booking request and confirms the appointment."
            className="hidden w-full max-w-[380px] rounded-[2rem] shadow-xl motion-reduce:block"
          />
        </Reveal>
      </div>
    </section>
  );
}
