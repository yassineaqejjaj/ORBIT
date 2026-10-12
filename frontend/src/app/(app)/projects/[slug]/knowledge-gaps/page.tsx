import type { Metadata } from "next";
import { Suspense } from "react";

import { KnowledgeGapsView } from "@/components/knowledge-gaps/knowledge-gaps-view";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Lacunes de connaissance" };

function KnowledgeGapsFallback() {
  return (
    <div className="grid gap-5" aria-busy="true" aria-label="Chargement des lacunes de connaissance">
      <div className="flex items-start gap-3">
        <Skeleton className="size-9 rounded-lg" />
        <div className="grid flex-1 gap-2">
          <Skeleton className="h-6 w-56" />
          <Skeleton className="h-4 w-full max-w-xl" />
        </div>
      </div>
      <Skeleton className="h-64 rounded-xl" />
    </div>
  );
}

export default function KnowledgeGapsPage() {
  return (
    <Suspense fallback={<KnowledgeGapsFallback />}>
      <KnowledgeGapsView />
    </Suspense>
  );
}
