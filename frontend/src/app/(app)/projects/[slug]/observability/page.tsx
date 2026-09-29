import { Suspense } from "react";
import type { Metadata } from "next";

import { ObservabilityView } from "@/components/observability/observability-view";

export const metadata: Metadata = { title: "Observabilité" };

export default function ObservabilityPage() {
  // `useSearchParams` (?days=) requires a Suspense boundary.
  return (
    <Suspense fallback={null}>
      <ObservabilityView />
    </Suspense>
  );
}
