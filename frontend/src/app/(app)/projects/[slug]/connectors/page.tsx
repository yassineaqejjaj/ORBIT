import type { Metadata } from "next";
import { Suspense } from "react";

import { ConnectorsView } from "@/components/connectors/connectors-view";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Connecteurs" };

function ConnectorsFallback() {
  return (
    <div className="grid gap-5" aria-busy="true" aria-label="Chargement des connecteurs">
      <div className="flex items-start gap-3">
        <Skeleton className="size-9 rounded-lg" />
        <div className="grid flex-1 gap-2">
          <Skeleton className="h-6 w-56" />
          <Skeleton className="h-4 w-full max-w-xl" />
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Skeleton className="h-36 rounded-xl" />
        <Skeleton className="h-36 rounded-xl" />
      </div>
    </div>
  );
}

export default function ConnectorsPage() {
  return (
    <Suspense fallback={<ConnectorsFallback />}>
      <ConnectorsView />
    </Suspense>
  );
}
