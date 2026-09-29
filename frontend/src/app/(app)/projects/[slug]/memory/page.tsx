import type { Metadata } from "next";
import { Suspense } from "react";

import { MemoryExplorer } from "@/components/memory/memory-explorer";
import { MemoryItemCardSkeleton } from "@/components/memory/memory-item-card";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Mémoire" };

function MemoryPageFallback() {
  return (
    <div className="grid gap-5" aria-busy="true" aria-label="Chargement de la mémoire">
      <div className="flex items-start gap-3">
        <Skeleton className="size-9 rounded-lg" />
        <div className="grid flex-1 gap-2">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-4 w-full max-w-xl" />
        </div>
      </div>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div className="grid gap-2.5">
          <Skeleton className="h-40 rounded-xl" />
          {Array.from({ length: 4 }, (_, i) => (
            <MemoryItemCardSkeleton key={i} />
          ))}
        </div>
        <Skeleton className="hidden h-[32rem] rounded-xl lg:block" />
      </div>
    </div>
  );
}

export default function MemoryPage() {
  return (
    <Suspense fallback={<MemoryPageFallback />}>
      <MemoryExplorer />
    </Suspense>
  );
}
