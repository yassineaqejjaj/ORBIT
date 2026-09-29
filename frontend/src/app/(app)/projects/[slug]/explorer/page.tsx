import { Suspense } from "react";
import type { Metadata } from "next";

import { ExplorerView } from "@/components/explorer/explorer-view";

export const metadata: Metadata = { title: "Explorateur de contexte" };

export default function ExplorerPage() {
  // `useSearchParams` (?request=, ?base=, ?version=) requires a Suspense boundary.
  return (
    <Suspense fallback={null}>
      <ExplorerView />
    </Suspense>
  );
}
