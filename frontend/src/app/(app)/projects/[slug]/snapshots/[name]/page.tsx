import type { Metadata } from "next";
import { Camera } from "lucide-react";

import { UnderConstruction } from "@/components/layout/under-construction";

export const metadata: Metadata = { title: "Snapshot" };

export default function SnapshotDetailPage() {
  return (
    <UnderConstruction
      icon={<Camera />}
      title="Snapshot"
      description="Versions d'un snapshot de contexte, contenu et éléments épinglés."
      upcoming={["Contenu Markdown et citations de chaque version", "Diff entre deux versions"]}
    />
  );
}
