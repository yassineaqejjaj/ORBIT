import type { Metadata } from "next";
import { Activity } from "lucide-react";

import { UnderConstruction } from "@/components/layout/under-construction";

export const metadata: Metadata = { title: "Observabilité" };

export default function ObservabilityPage() {
  return (
    <UnderConstruction
      icon={<Activity />}
      title="Observabilité"
      description="Latence, tokens, coûts estimés, motifs d'exclusion et traces des contextes servis."
      upcoming={["Séries quotidiennes : requêtes, latence p50/p95, tokens, coût", "Répartition des exclusions par motif et des inclusions par type", "Export NDJSON des traces pour l'évaluation (FORGE)"]}
    />
  );
}
