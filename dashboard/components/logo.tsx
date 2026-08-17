import Image from "next/image";

import { cn } from "@/lib/utils";

/**
 * The Qonvo mark: a speech bubble holding a voice waveform, which is the whole
 * brand idea, chat and voice being the two ways Qonvo talks. The standard mark
 * carries its own Signal Green tile, so it reads on Paper and on Ink alike and
 * needs no per-theme swap.
 */
export function Logo({
  className,
  showWordmark = true,
}: {
  className?: string;
  showWordmark?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <Image
        src="/logo-mark.png"
        alt="Qonvo"
        width={28}
        height={28}
        className="h-7 w-7 rounded-lg"
        priority
      />
      {showWordmark ? (
        <span className="font-display text-lg font-extrabold lowercase tracking-tight">
          qonvo
        </span>
      ) : null}
    </span>
  );
}
