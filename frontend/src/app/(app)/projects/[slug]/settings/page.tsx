import { Suspense } from "react";
import type { Metadata } from "next";

import { SettingsView } from "@/components/settings/settings-view";

export const metadata: Metadata = { title: "Paramètres" };

export default function SettingsPage() {
  // `useSearchParams` (?tab=, ?action=, ?page=) requires a Suspense boundary.
  return (
    <Suspense fallback={null}>
      <SettingsView />
    </Suspense>
  );
}
