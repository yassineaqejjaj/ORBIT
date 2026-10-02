import { Suspense } from "react";
import type { Metadata } from "next";

import { AskView } from "@/components/ask/ask-view";

export const metadata: Metadata = { title: "Demander à ORBIT" };

export default function AskPage() {
  // `useSearchParams` (?conversation=) requires a Suspense boundary.
  return (
    <Suspense fallback={null}>
      <AskView />
    </Suspense>
  );
}
