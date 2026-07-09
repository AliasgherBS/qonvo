import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

type Tone = "default" | "success" | "warning" | "danger" | "info";

const toneClasses: Record<Tone, string> = {
  default: "bg-surface-muted text-foreground",
  success: "bg-primary/15 text-primary-strong",
  warning: "bg-warning/15 text-warning",
  danger: "bg-danger/15 text-danger",
  info: "bg-accent/25 text-accent-foreground",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
}

export function Badge({ className, tone = "default", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold",
        toneClasses[tone],
        className,
      )}
      {...props}
    />
  );
}
