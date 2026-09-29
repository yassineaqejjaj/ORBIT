import type { Metadata } from "next";
import { Suspense } from "react";

import { SnapshotDetailSkeleton, SnapshotDetailView } from "@/components/snapshots/snapshot-detail-view";

function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

export async function generateMetadata({ params }: { params: Promise<{ name: string }> }): Promise<Metadata> {
  const { name } = await params;
  return { title: `Snapshot ${safeDecode(name)}` };
}

export default function SnapshotDetailPage() {
  // `useSearchParams` (?v=, ?mode=compare&from=&to=, ?tab=) requires a Suspense boundary.
  return (
    <Suspense fallback={<SnapshotDetailSkeleton />}>
      <SnapshotDetailView />
    </Suspense>
  );
}
