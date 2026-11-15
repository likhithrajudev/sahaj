import { cn } from "@/lib/utils";

/** Material Symbols Rounded (self-hosted subset: add new names to scripts/icons.sh). Decorative unless labelled. */
export function Icon({ name, size = 24, fill = false, className, label }: {
  name: string; size?: number; fill?: boolean; className?: string; label?: string;
}) {
  return (
    <span
      className={cn("icon", fill && "icon-fill", className)}
      style={{ fontSize: size }}
      aria-hidden={label ? undefined : true}
      role={label ? "img" : undefined}
      aria-label={label}
    >
      {name}
    </span>
  );
}
