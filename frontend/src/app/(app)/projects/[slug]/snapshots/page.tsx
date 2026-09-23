import type { Metadata } from "next";
import { Camera } from "lucide-react";

import { UnderConstruction } from "@/components/layout/under-construction";

export const metadata: Metadata = { title: "Snapshots" };

export default function SnapshotsPage() {
  return (
    <UnderConstruction
      icon={<Camera />}
      title="Snapshots"
      description="Contextes partagés, versionnés et immuables, réutilisables d'un agent à l'autre."
      upcoming={["Liste des snapshots et de leurs versions", "Comparaison entre versions (ajouts, retraits, inchangés)"]}
    />
  );
}
