import type { Metadata } from "next";
import { Suspense } from "react";

import { InboxView } from "@/components/inbox/inbox-view";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Tri de la mémoire" };

function InboxFallback() {
  return (
    <div className="grid gap-5" aria-busy="true" aria-label="Chargement du tri de la mémoire">
      <div className="flex items-start gap-3">
        <Skeleton className="size-9 rounded-lg" />
        <div className="grid flex-1 gap-2">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-full max-w-xl" />
        </div>
      </div>
      <Skeleton className="h-9 w-72" />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <div className="grid gap-2">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-20 rounded-lg" />
          ))}
        </div>
        <Skeleton className="hidden h-96 rounded-xl lg:block" />
      </div>
    </div>
  );
}

export default function InboxPage() {
  return (
    <Suspense fallback={<InboxFallback />}>
      <InboxView />
    </Suspense>
  );
}
