import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Indian digit grouping: 1200000 -> "₹12,00,000". */
export function rupees(amount: number): string {
  return "₹" + Math.round(amount).toLocaleString("en-IN");
}
