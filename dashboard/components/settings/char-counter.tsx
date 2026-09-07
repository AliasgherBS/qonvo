"use client";

import { cn } from "@/lib/utils";

/**
 * `used / cap` under a capped field.
 *
 * The API rejects rather than truncates, which is the right behaviour and a
 * bad surprise on its own: someone writes for ten minutes, hits save, and is
 * told to cut 1,140 characters they can no longer see the end of. The counter
 * turns this into something you notice while typing.
 *
 * It never disables the field. Being unable to finish a sentence before
 * deciding what to cut is worse than being over by forty characters, so the
 * over state is loud and the *save* is what refuses.
 */
export function CharCounter({ value, max }: { value: string; max: number }) {
  const used = value.length;
  const ratio = used / max;
  const over = used > max;
  // 80% is where a warning is still actionable: enough room left to finish the
  // thought and then trim, rather than a colour change at the moment it is
  // already too late to matter.
  const near = !over && ratio >= 0.8;

  return (
    <p
      className={cn(
        "text-right text-xs tabular-nums",
        over ? "font-semibold text-destructive" : near ? "text-amber-600" : "text-muted-foreground",
      )}
      // Announced on change, not on every keystroke, so a screen reader is told
      // when it starts to matter rather than read a number 2,000 times.
      aria-live={over || near ? "polite" : "off"}
    >
      {used.toLocaleString()} / {max.toLocaleString()}
      {over ? `, ${(used - max).toLocaleString()} too many` : ""}
    </p>
  );
}
