import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Indian digit grouping: 1200000 -> "₹12,00,000". */
export function rupees(amount: number): string {
  return "₹" + Math.round(amount).toLocaleString("en-IN");
}

/** "₹20 lakh", "₹1.5 crore", "₹45,000" for prose next to the exact figure. */
export function rupeesWords(amount: number): string {
  if (amount >= 1_00_00_000) return `₹${+(amount / 1_00_00_000).toFixed(2)} crore`;
  if (amount >= 1_00_000) return `₹${+(amount / 1_00_000).toFixed(2)} lakh`;
  return rupees(amount);
}

/** Backend text writes money as "Rs 5,00,000"; show the rupee sign. */
export function withRupeeSign(text: string): string {
  return text.replace(/\bRs\.?\s?(?=\d)/g, "₹");
}

/** "waiting period for pre-existing diseases" -> "Waiting period for pre-existing diseases" */
export function sentenceCase(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

/** The backend's catalogue and documents mark fictional data "(SAMPLE)" / "(sample data)"; the UI doesn't show it. */
export function clean(text: string): string {
  return text.replace(/\s*\((?:SAMPLE|sample data)\)/gi, "");
}
