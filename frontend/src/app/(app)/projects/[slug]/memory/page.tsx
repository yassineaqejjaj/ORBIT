import type { Metadata } from "next";
import { Brain } from "lucide-react";

import { UnderConstruction } from "@/components/layout/under-construction";

export const metadata: Metadata = { title: "Mémoire" };

export default function MemoryPage() {
  return (
    <UnderConstruction
      icon={<Brain />}
      title="Mémoire"
      description="Décisions, besoins, contraintes, risques, faits et préférences du projet, versionnés et gouvernés."
      upcoming={["Validation, remplacement, obsolescence et restauration", "Historique complet et provenance de chaque élément", "Graphe des relations (remplace, contredit, dérivé de…)"]}
    />
  );
}
