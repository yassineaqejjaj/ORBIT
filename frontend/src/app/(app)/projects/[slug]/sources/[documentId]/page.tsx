import { Suspense } from "react";
import type { Metadata } from "next";

import { DocumentDetailView } from "@/components/sources/document-detail-view";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Document" };

function DocumentFallback() {
  return (
    <div className="grid gap-6" aria-busy="true" aria-label="Chargement du document">
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-8 w-96 max-w-full" />
      <Skeleton className="h-24 rounded-xl" />
      <Skeleton className="h-80 rounded-xl" />
    </div>
  );
}

export default function DocumentPage() {
  return (
    <Suspense fallback={<DocumentFallback />}>
      <DocumentDetailView />
    </Suspense>
  );
}
