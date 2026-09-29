import { Star } from "lucide-react";

import { cn } from "@/lib/utils";

/** Read-only star rating. */
export function StarRating({ value, size = "sm", className }: { value: number | null | undefined; size?: "sm" | "md"; className?: string }) {
  const v = typeof value === "number" ? value : 0;
  return (
    <span
      className={cn("inline-flex items-center gap-0.5", className)}
      role="img"
      aria-label={typeof value === "number" ? `Note ${v.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} sur 5` : "Non noté"}
    >
      {[1, 2, 3, 4, 5].map((n) => (
        <Star
          key={n}
          aria-hidden
          className={cn(
            size === "sm" ? "size-3" : "size-4",
            n <= Math.round(v) ? "fill-amber-400 text-amber-400" : "fill-transparent text-border-strong",
          )}
        />
      ))}
    </span>
  );
}
