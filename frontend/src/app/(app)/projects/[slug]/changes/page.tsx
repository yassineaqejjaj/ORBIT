import type { Metadata } from "next";
import { Suspense } from "react";

import { ChangesView } from "@/components/changes/changes-view";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Fil des changements" };

function ChangesFallback() {
  return (
    <div className="grid gap-5" aria-busy="true" aria-label="Chargement du fil des changements">
      <div className="flex items-start gap-3">
        <Skeleton className="size-9 rounded-lg" />
        <div className="grid flex-1 gap-2">
          <Skeleton className="h-6 w-56" />
          <Skeleton className="h-4 w-full max-w-xl" />
        </div>
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,8fr)_minmax(0,4fr)]">
        <Skeleton className="h-96 rounded-xl" />
        <Skeleton className="hidden h-72 rounded-xl lg:block" />
      </div>
    </div>
  );
}

export default function ChangesPage() {
  return (
    <Suspense fallback={<ChangesFallback />}>
      <ChangesView />
    </Suspense>
  );
}
