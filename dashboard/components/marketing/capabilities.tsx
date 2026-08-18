import { BookOpen, CalendarCheck, ClipboardList, UserRoundCheck } from "lucide-react";

import { Reveal, RevealGroup, RevealItem } from "@/components/marketing/reveal";

/**
 * Four items, four cells, no empty tiles. On a 3-column grid that means row
 * one is wide + single and row two is single + wide, which fills both rows
 * exactly while still giving the grid rhythm rather than being identical
 * cards. Changing any `wide` flag without rechecking the arithmetic leaves a
 * blank tile, which is what happened the first time.
 *
 * Cell three says Google Sheet, not CRM. CRM sync is not shipped; the promo
 * video's "logs the lead to your CRM" frame is ahead of the product and is
 * answered as roadmap in the FAQ instead.
 */
const CAPABILITIES = [
  {
    icon: BookOpen,
    title: "Answers from your own knowledge",
    body: "Add your hours, prices and policies once. Qonvo answers from those, never from guesswork, and says so plainly when something falls outside what it knows.",
    wide: true,
  },
  {
    icon: CalendarCheck,
    title: "Books appointments",
    body: "Connect Google Calendar. Qonvo checks what is actually free, so it will not double-book you.",
    wide: false,
  },
  {
    icon: ClipboardList,
    title: "Takes orders and logs leads",
    body: "Every order and every lead lands in a Google Sheet you control.",
    wide: false,
  },
  {
    icon: UserRoundCheck,
    title: "Hands over to you",
    body: "When a conversation needs a person, Qonvo steps back and goes quiet for that chat, so you never end up talking over each other.",
    wide: true,
  },
];

export function Capabilities() {
  return (
    <section className="border-t border-border/60">
      <div className="mx-auto w-full max-w-7xl px-4 py-24 sm:py-32">
        <Reveal>
          <h2 className="max-w-2xl text-4xl font-extrabold leading-tight tracking-tight md:text-5xl">
            It does not just chat.
            <br />
            It does the <span className="text-primary">work.</span>
          </h2>
        </Reveal>

        <RevealGroup className="mt-14 grid gap-4 md:grid-cols-3" stagger={0.09}>
          {CAPABILITIES.map(({ icon: Icon, title, body, wide }) => (
            <RevealItem key={title} className={wide ? "md:col-span-2" : ""}>
              <div
                className={`flex h-full flex-col rounded-3xl border border-border/60 p-7 ${
                  wide
                    ? "bg-gradient-to-br from-primary/12 via-surface to-surface"
                    : "bg-surface/60"
                }`}
              >
                <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/15 text-primary">
                  <Icon className="h-5 w-5" />
                </span>
                <h3 className="mt-5 text-lg font-bold tracking-tight">{title}</h3>
                <p className="mt-2 text-muted-foreground">{body}</p>
              </div>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  );
}
