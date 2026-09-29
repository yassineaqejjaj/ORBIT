import type { Metadata } from "next";

import { SnapshotListView } from "@/components/snapshots/snapshot-list-view";

export const metadata: Metadata = { title: "Snapshots" };

export default function SnapshotsPage() {
  return <SnapshotListView />;
}
