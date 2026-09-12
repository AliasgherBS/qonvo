"use client";

import { Pause, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Marquee, Reveal } from "@/components/marketing/reveal";
import { cn } from "@/lib/utils";

/**
 * One section where the voice sample and the language claim are the same
 * control, replacing the two that used to sit next to each other.
 *
 * Separately they each half-made the argument. The voice section played one
 * English clip, so "replies in your customer's language" was a sentence next
 * to a sample that only ever demonstrated English. The languages section was a
 * marquee of greetings, which proves we can render a script and nothing about
 * whether the rep can speak it. A visitor who doubted the multilingual claim
 * could not check it, and that is the claim most worth doubting.
 *
 * Together they are checkable: pick a language, hear the same sentence spoken
 * in it. The greetings marquee stays below as the breadth claim, because five
 * chips is the playable set and not the supported set.
 *
 * **Every clip is the same booking exchange**, deliberately. A different line
 * per language would be five demos; the same line is one demo in five
 * languages, and the sameness is the whole point being made.
 *
 * The audio is real product output, generated with the same class of
 * text-to-speech the rep uses, so what a visitor hears is what a customer
 * would hear rather than a voice actor reading marketing copy.
 */

/**
 * The line each clip actually speaks, and the transcript shown under it.
 *
 * These strings are the ones that were sent to the synthesiser, not a
 * translation made afterwards to caption them. That matters: a caption
 * produced independently of the audio is a caption that can be wrong, and
 * nobody proofreading this page in English would catch it.
 *
 * `dir` is carried per entry rather than inferred, and the transcript is
 * rendered in a `p`. Headings use the display stack, which names no Noto face,
 * so an Urdu or Hindi line set as a heading renders as tofu boxes. Body text
 * inherits the fallback chain that includes both.
 */
const SAMPLES = [
  {
    code: "en",
    label: "English",
    lang: "en",
    dir: "ltr",
    src: "/voice/reply-en.mp3",
    line: "Hi, yes, we are open until eight tonight. I have a slot free at 6:30. If that suits you, shall I book it in for you?",
  },
  {
    code: "ur",
    label: "اردو",
    lang: "ur",
    dir: "rtl",
    src: "/voice/reply-ur.mp3",
    line: "جی ہاں، ہم آج رات آٹھ بجے تک کھلے ہیں۔ میرے پاس ساڑھے چھ بجے ایک سلاٹ خالی ہے۔ اگر آپ کو مناسب ہو تو کیا میں آپ کے لیے بک کر دوں؟",
  },
  {
    code: "ar",
    label: "العربية",
    lang: "ar",
    dir: "rtl",
    src: "/voice/reply-ar.mp3",
    line: "أهلاً، نعم، نحن مفتوحون حتى الثامنة مساء اليوم. لدي موعد شاغر في السادسة والنصف. إذا كان ذلك يناسبك، هل أحجزه لك؟",
  },
  {
    code: "hi",
    label: "हिन्दी",
    lang: "hi",
    dir: "ltr",
    src: "/voice/reply-hi.mp3",
    line: "जी हाँ, हम आज रात आठ बजे तक खुले हैं। मेरे पास साढ़े छह बजे एक स्लॉट खाली है। अगर आपको ठीक लगे, तो क्या मैं आपके लिए बुक कर दूँ?",
  },
  {
    code: "fr",
    label: "Français",
    lang: "fr",
    dir: "ltr",
    src: "/voice/reply-fr.mp3",
    line: "Bonjour, oui, nous sommes ouverts jusqu'à vingt heures ce soir. J'ai un créneau libre à dix-huit heures trente. Si cela vous convient, je vous le réserve ?",
  },
] as const;

/**
 * The wider claim, kept as a marquee because it is breadth rather than proof.
 *
 * Fourteen entries, not eight (teardown L6): eight pills were narrower than a
 * desktop viewport, so Bonjour, Olá and Merhaba each appeared twice on one
 * screen and the loop read as a rendering bug rather than as motion. The strip
 * has to be wider than the widest viewport for the seam to stay off screen.
 * It leads with the market it is sold into.
 *
 * Nothing here is in a script the two loaded Noto faces do not cover, which is
 * deliberate. A Cyrillic or CJK greeting would need a third face or it renders
 * as tofu, and a tofu box is a worse advert for speaking a customer's language
 * than not listing it.
 *
 * Keyed on the text, not the language: Urdu appears twice, once in its own
 * script and once in the Latin transliteration people actually type on
 * WhatsApp, and two pills keyed `ur` would collide.
 */
const GREETINGS = [
  { text: "Hello", lang: "en" },
  { text: "السلام علیکم", lang: "ur" },
  { text: "Assalam o alaikum", lang: "ur-Latn" },
  { text: "کی حال اے", lang: "pa-Arab" },
  { text: "ستړی مه شې", lang: "ps" },
  { text: "ڪيئن آهيو", lang: "sd" },
  { text: "مرحبا", lang: "ar" },
  { text: "नमस्ते", lang: "hi" },
  { text: "Hola", lang: "es" },
  { text: "Bonjour", lang: "fr" },
  { text: "Olá", lang: "pt" },
  { text: "Merhaba", lang: "tr" },
  { text: "Ciao", lang: "it" },
  { text: "Hallo", lang: "de" },
];

/** Fixed, not random, so it is stable across renders and server and client agree. */
const BARS = [
  18, 34, 52, 30, 66, 44, 78, 40, 58, 26, 70, 48, 36, 62, 22, 54, 38, 68, 30, 46,
];

export function VoiceSampler() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [selected, setSelected] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [unavailable, setUnavailable] = useState(false);

  // Set when a language is picked mid-playback, so the new clip starts on its
  // own. Switching language while listening is a comparison, and stopping the
  // audio to make the visitor press play again breaks the one thing this
  // section exists to let them do.
  //
  // A ref rather than state: it is read inside the effect that reacts to the
  // change, and as state it would be a second render and a race with it.
  const resumeRef = useRef(false);

  const sample = SAMPLES[selected];

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const onTime = () =>
      setProgress(audio.duration > 0 ? audio.currentTime / audio.duration : 0);
    const onEnd = () => {
      setPlaying(false);
      setProgress(0);
    };
    // A missing or blocked file must not leave a button that does nothing,
    // which is the state this section started in (teardown L7).
    const onError = () => {
      setUnavailable(true);
      setPlaying(false);
    };

    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("ended", onEnd);
    audio.addEventListener("error", onError);
    return () => {
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("ended", onEnd);
      audio.removeEventListener("error", onError);
    };
  }, []);

  // Reacts to the language change rather than doing the work inside the click
  // handler, because the `src` attribute is only on the element after React
  // has re-rendered. Calling load() in the handler would reload the clip that
  // is being navigated away from.
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.load();
    if (!resumeRef.current) return;
    resumeRef.current = false;
    void audio
      .play()
      .then(() => setPlaying(true))
      .catch(() => setUnavailable(true));
  }, [selected]);

  function pick(index: number) {
    if (index === selected) return;
    const audio = audioRef.current;
    resumeRef.current = playing;
    audio?.pause();
    setPlaying(false);
    setProgress(0);
    // Cleared on purpose: one language failing to load says nothing about the
    // next, and leaving the fallback up would strand the whole control.
    setUnavailable(false);
    setSelected(index);
  }

  async function toggle() {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      audio.pause();
      setPlaying(false);
      return;
    }
    try {
      await audio.play();
      setPlaying(true);
    } catch {
      // Autoplay policies reject a play() that is not user-driven; this one is,
      // so a rejection here means the file will not decode.
      setUnavailable(true);
    }
  }

  function seek(fraction: number) {
    const audio = audioRef.current;
    if (!audio || !audio.duration) return;
    audio.currentTime = audio.duration * fraction;
    setProgress(fraction);
  }

  const played = Math.round(progress * BARS.length);

  return (
    <section className="bg-brand-paper py-24 text-brand-surface-900 sm:py-32">
      <div className="mx-auto w-full max-w-3xl px-4 text-center">
        <Reveal>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-brand-surface-700">
            Voice, in their language
          </p>
        </Reveal>

        <Reveal delay={0.08}>
          <h2 className="mt-4 text-4xl font-extrabold leading-tight tracking-tight md:text-5xl">
            Send a voice note. Get one back.
          </h2>
        </Reveal>

        <Reveal delay={0.14}>
          <p className="mx-auto mt-5 max-w-xl text-lg leading-relaxed text-brand-surface-700">
            The same customer question, answered out loud. Pick a language and
            hear what your customer would hear.
          </p>
        </Reveal>

        {/* Buttons with aria-pressed rather than a radiogroup: each one is a
            control that swaps what the player holds, and a visitor arrowing
            through a radiogroup would load five clips on the way past. */}
        <Reveal delay={0.2}>
          <div className="mt-9 flex flex-wrap items-center justify-center gap-2">
            {SAMPLES.map((item, index) => (
              <button
                key={item.code}
                type="button"
                lang={item.lang}
                onClick={() => pick(index)}
                aria-pressed={index === selected}
                className={cn(
                  "rounded-full px-5 py-2.5 text-base font-bold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-surface-900 focus-visible:ring-offset-2 focus-visible:ring-offset-brand-paper",
                  index === selected
                    ? "bg-brand-surface-900 text-brand-paper"
                    : "bg-brand-paper-dim text-brand-surface-700 hover:bg-brand-surface-900/10",
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
        </Reveal>

        <Reveal delay={0.26}>
          {unavailable ? (
            /* The original static waveform, which is the honest fallback: a
               play button that does nothing is worse than no play button. */
            <div
              className="mx-auto mt-10 flex h-20 max-w-md items-center justify-center gap-1.5"
              aria-hidden="true"
            >
              {BARS.map((h, i) => (
                <span
                  key={i}
                  className="w-1.5 rounded-full bg-brand-surface-900/40"
                  style={{ height: `${h}%` }}
                />
              ))}
            </div>
          ) : (
            <div className="mx-auto mt-10 flex max-w-md items-center gap-4">
              <button
                type="button"
                onClick={toggle}
                aria-label={
                  playing
                    ? `Pause the ${sample.label} reply`
                    : `Play the ${sample.label} reply`
                }
                className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-brand-surface-900 text-brand-paper transition-transform hover:scale-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-surface-900 focus-visible:ring-offset-2 focus-visible:ring-offset-brand-paper active:scale-95"
              >
                {playing ? (
                  <Pause className="h-5 w-5" />
                ) : (
                  // Nudged right, because a triangle centred on its bounding
                  // box reads as sitting left of centre.
                  <Play className="ml-0.5 h-5 w-5" />
                )}
              </button>

              {/* A button rather than a div: it is a seek control, so it has to
                  be reachable and operable without a pointer. The bars track
                  playback and do not loop -- an animation that runs on its own
                  is decoration, bars that fill as the clip plays are progress,
                  which is what makes a nine-second clip feel finishable. */}
              <button
                type="button"
                onClick={(e) => {
                  const box = e.currentTarget.getBoundingClientRect();
                  seek(Math.min(1, Math.max(0, (e.clientX - box.left) / box.width)));
                }}
                aria-label="Seek within the sample"
                className="flex h-20 flex-1 items-center justify-center gap-1.5 rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-surface-900"
              >
                {BARS.map((h, i) => (
                  <span
                    key={i}
                    className={cn(
                      "w-1.5 rounded-full transition-colors",
                      i < played ? "bg-brand-surface-900" : "bg-brand-surface-900/25",
                    )}
                    style={{ height: `${h}%` }}
                  />
                ))}
              </button>
            </div>
          )}

          {/* aria-live, because switching language changes this text without
              moving focus, and a screen reader user would otherwise get new
              audio with no indication of what it is. */}
          <p
            lang={sample.lang}
            dir={sample.dir}
            aria-live="polite"
            /* The height of the tallest transcript is reserved, so switching
               language cannot shift everything below it. Measured: 3 lines from
               768px up (Urdu and French are the long ones) and 4 below, at
               leading-relaxed, so the values are 3 and 4 times 1.625em. Without
               this, picking Urdu pushed the marquee down 29px and the section
               visibly jumped under the pointer that caused it. */
            className="mx-auto mt-6 min-h-[6.5em] max-w-lg text-balance text-lg font-semibold leading-relaxed text-brand-surface-900 md:min-h-[4.875em]"
          >
            {sample.line}
          </p>
          <p className="mx-auto mt-3 max-w-md text-sm text-brand-surface-700">
            What the rep said back, in {sample.label}.
          </p>
        </Reveal>
      </div>

      {/* preload="none" on purpose. Most visitors will never press play, so no
          clip is part of the page weight until somebody asks for one.

          Deliberately NOT keyed on the language. A key here would make React
          destroy and recreate the element on every switch, so the listeners
          bound once on mount would stay attached to a discarded node and
          progress, ended and error would all stop working from the second
          language onward. The element is stable; only its src changes, and the
          effect above calls load(). */}
      <audio ref={audioRef} src={sample.src} preload="none" />

      <Reveal delay={0.32} className="mt-16">
        <Marquee>
          {GREETINGS.map(({ text, lang }) => (
            <span
              key={text}
              lang={lang}
              className="rounded-full bg-brand-surface-900 px-7 py-3 text-xl font-bold text-brand-paper"
            >
              {text}
            </span>
          ))}
        </Marquee>
      </Reveal>

      <div className="mx-auto mt-12 w-full max-w-7xl px-4 text-center">
        <Reveal delay={0.38}>
          <p className="mx-auto max-w-xl text-lg text-brand-surface-700">
            It detects the language your customer wrote or spoke in, and replies
            in it.
          </p>
        </Reveal>
      </div>
    </section>
  );
}
