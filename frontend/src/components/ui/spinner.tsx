import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

export function Spinner({ className, label = "Chargement…" }: { className?: string; label?: string }) {
  return (
    <span role="status" className="inline-flex items-center">
      <Loader2 className={cn("size-4 animate-spin text-muted-foreground", className)} aria-hidden />
      <span className="sr-only">{label}</span>
    </span>
  );
}
