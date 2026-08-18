"use client";

import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";

const EASE = [0.16, 1, 0.3, 1] as const;

/** One element rising into place as it enters the viewport. */
export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.25 }}
      transition={{ duration: 0.6, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

/** Parent for staggered children. Pair with RevealItem. */
export function RevealGroup({
  children,
  className,
  stagger = 0.08,
}: {
  children: ReactNode;
  className?: string;
  stagger?: number;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? false : "hidden"}
      whileInView="shown"
      viewport={{ once: true, amount: 0.2 }}
      variants={{ hidden: {}, shown: { transition: { staggerChildren: stagger } } }}
    >
      {children}
    </motion.div>
  );
}

export function RevealItem({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      variants={{
        hidden: { opacity: 0, y: 20 },
        shown: { opacity: 1, y: 0, transition: { duration: 0.55, ease: EASE } },
      }}
    >
      {children}
    </motion.div>
  );
}

/**
 * Continuous horizontal scroll. Renders its children twice so the loop has no
 * visible seam. Under reduced motion it collapses to a single static row,
 * because an endlessly moving strip is precisely what that setting exists to
 * stop.
 */
export function Marquee({
  children,
  speed = 32,
}: {
  children: ReactNode;
  speed?: number;
}) {
  const reduce = useReducedMotion();

  if (reduce) {
    return <div className="flex flex-wrap justify-center gap-3">{children}</div>;
  }

  return (
    <div className="relative flex overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_12%,black_88%,transparent)]">
      {[0, 1].map((copy) => (
        <motion.div
          key={copy}
          className="flex shrink-0 items-center gap-3 pr-3"
          animate={{ x: ["0%", "-100%"] }}
          transition={{ duration: speed, ease: "linear", repeat: Infinity }}
          aria-hidden={copy === 1}
        >
          {children}
        </motion.div>
      ))}
    </div>
  );
}
