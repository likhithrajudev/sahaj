import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/** Pill buttons from the design: 52 px primary/outline, 40 px small, text links. */
const button = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap font-semibold transition-colors disabled:opacity-50 disabled:pointer-events-none",
  {
    variants: {
      variant: {
        primary: "bg-primary text-on-primary hover:bg-primary-strong",
        outline: "border-[1.5px] border-primary text-primary bg-surface hover:bg-primary-soft",
        neutral: "border border-line-2 text-ink bg-surface hover:bg-surface-2",
        danger: "bg-error text-white hover:opacity-90",
        soft: "bg-primary-soft text-primary hover:opacity-90",
        link: "text-primary underline-offset-2 hover:underline",
      },
      size: {
        lg: "h-[52px] rounded-full px-6 text-[17px]",
        md: "h-11 rounded-full px-5 text-[15px]",
        sm: "h-9 rounded-[10px] px-3 text-sm",
        inline: "min-h-10 px-0 text-[15px]",
      },
    },
    defaultVariants: { variant: "primary", size: "lg" },
  },
);

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof button>;

export function Button({ className, variant, size, type = "button", ...props }: ButtonProps) {
  return <button type={type} className={cn(button({ variant, size }), className)} {...props} />;
}
