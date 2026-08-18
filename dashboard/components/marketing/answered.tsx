import Image from "next/image";

import { Reveal } from "@/components/marketing/reveal";

/**
 * Split, mirrored from the hero: image left, copy right. Two splits total on
 * the page and they are not adjacent, so the zigzag cap is respected.
 *
 * The image is a real frame from the brand's promo video, not a hand-built
 * fake chat UI.
 */
export function Answered() {
  return (
    <section className="mx-auto grid w-full max-w-7xl items-center gap-12 px-4 py-24 sm:py-32 lg:grid-cols-2">
      <Reveal className="order-2 flex justify-center lg:order-1 lg:justify-start">
        <Image
          src="/conversation.png"
          alt="A WhatsApp chat: the customer asks for a cleaning, Qonvo offers 11:30 or 3:00, the customer picks 3pm, and Qonvo confirms the booking and a reminder."
          width={608}
          height={1080}
          className="w-full max-w-[360px] rounded-[2rem] shadow-xl"
        />
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
