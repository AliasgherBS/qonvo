"use client";

import { Pause, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * The waveform, playable (teardown L7, and one of the three D2 treatments).
 *
 * A page selling voice had no voice on it: a decorative static waveform and
 * nothing to press. The section's own comment said there was deliberately no
 * play button because there was no audio file, which was honest and left the
 * strongest claim on the page unevidenced.
 *
 * There is a file now. It is the rep's side of a real exchange, generated with
 * the same class of text-to-speech the product uses, so what a visitor hears
 * is what a customer would hear rather than a voice actor reading marketing
 * copy.
 *
 * **The bars track playback, they do not loop.** An animation that runs on its
 * own is decoration again; bars that fill as the clip plays are a progress
 * indicator, which is the thing that makes a nine-second clip feel finishable.
 * They are also clickable, so it is a seek bar.
 *
 * `preload="none"` on purpose. The clip is 117 KB and most visitors will never
 * press play, so it is not part of the page weight until somebody asks for it.
 *
 * Reduced motion is respected by doing nothing extra: there is no ambient
 * animation to suppress, and progress is a state change rather than a
 * transition somebody could find uncomfortable.
 */

/** Fixed, not random, so it is stable across renders and server and client agree. */
const BARS = [
  18, 34, 52, 30, 66, 44, 78, 40, 58, 26, 70, 48, 36, 62, 22, 54, 38, 68, 30, 46,
];

export function VoicePlayer() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [unavailable, setUnavailable] = useState(false);

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
    // which is the state this section started in.
    const onError = () => setUnavailable(true);

    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("ended", onEnd);
    audio.addEventListener("error", onError);
    return () => {
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("ended", onEnd);
      audio.removeEventListener("error", onError);
    };
  }, []);

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

  if (unavailable) {
    // The original static waveform, which is the honest fallback.
    return (
      <div
        className="mx-auto mt-12 flex h-20 max-w-md items-center justify-center gap-1.5"
        aria-hidden="true"
      >
        {BARS.map((h, i) => (
          <span key={i} className="w-1.5 rounded-full bg-primary/70" style={{ height: `${h}%` }} />
        ))}
      </div>
    );
  }

  const played = Math.round(progress * BARS.length);

  return (
    <div className="mx-auto mt-12 flex max-w-md items-center gap-4">
      <button
        type="button"
        onClick={toggle}
        aria-label={playing ? "Pause the sample reply" : "Play a sample reply"}
        className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-transform hover:scale-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring active:scale-95"
      >
        {playing ? (
          <Pause className="h-5 w-5" />
        ) : (
          // Nudged right, because a triangle centred on its bounding box reads
          // as sitting left of centre.
          <Play className="ml-0.5 h-5 w-5" />
        )}
      </button>

      {/* A button rather than a div: it is a seek control, so it has to be
          reachable and operable without a pointer. */}
      <button
        type="button"
        onClick={(e) => {
          const box = e.currentTarget.getBoundingClientRect();
          seek(Math.min(1, Math.max(0, (e.clientX - box.left) / box.width)));
        }}
        aria-label="Seek within the sample"
        className="flex h-20 flex-1 items-center justify-center gap-1.5 rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {BARS.map((h, i) => (
          <span
            key={i}
            className={cn(
              "w-1.5 rounded-full transition-colors",
              i < played ? "bg-primary" : "bg-primary/25",
            )}
            style={{ height: `${h}%` }}
          />
        ))}
      </button>

      <audio ref={audioRef} src="/voice-reply.mp3" preload="none" />
    </div>
  );
}
