import { type ButtonHTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/utils";

type Variant = "primary" | "accent" | "secondary" | "outline" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const variantClasses: Record<Variant, string> = {
  primary: "bg-primary text-primary-foreground hover:bg-primary-strong",
  // Volt. The brand kit calls it "a spotlight, not a background", so this
  // variant is for the single loudest CTA on a page and nothing else.
  accent: "bg-accent text-accent-foreground hover:bg-brand-accent-500",
  secondary: "bg-surface-muted text-foreground hover:bg-border",
  outline: "border border-border-strong text-foreground hover:bg-surface-muted",
  ghost: "text-foreground hover:bg-surface-muted",
  danger: "bg-danger text-danger-foreground hover:opacity-90",
};

const sizeClasses: Record<Size, string> = {
  sm: "h-8 px-3.5 text-sm",
  md: "h-10 px-5 text-sm",
  lg: "h-12 px-6 text-base",
};

/** Button styling as a class string, for when the element must be an `<a>`/`<Link>`. */
export function buttonClasses({
  variant = "primary",
  size = "md",
  className,
}: { variant?: Variant; size?: Size; className?: string } = {}) {
  return cn(
    "inline-flex items-center justify-center gap-2 rounded-full font-semibold",
    // Tactile press feedback: the button gives slightly under the pointer.
    "transition-[colors,transform] duration-200 active:scale-[0.98]",
    "disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
    variantClasses[variant],
    sizeClasses[size],
    className,
  );
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", ...props }, ref) => {
    return (
      <button ref={ref} className={buttonClasses({ variant, size, className })} {...props} />
    );
  },
);
Button.displayName = "Button";
