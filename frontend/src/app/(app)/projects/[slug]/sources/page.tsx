import { Suspense } from "react";
import type { Metadata } from "next";

import { SourcesView } from "@/components/sources/sources-view";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Sources" };

function SourcesFallback() {
  return (
    <div className="grid gap-6" aria-busy="true" aria-label="Chargement des sources">
      <div className="grid gap-2">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-4 w-full max-w-2xl" />
      </div>
      <Skeleton className="h-10 w-full max-w-md" />
      <Skeleton className="h-96 rounded-xl" />
    </div>
  );
}

export default function SourcesPage() {
  return (
    <Suspense fallback={<SourcesFallback />}>
      <SourcesView />
    </Suspense>
  );
}
