import type { Metadata } from "next";
import { Telescope } from "lucide-react";

import { UnderConstruction } from "@/components/layout/under-construction";

export const metadata: Metadata = { title: "Explorateur de contexte" };

export default function ExplorerPage() {
  return (
    <UnderConstruction
      icon={<Telescope />}
      title="Explorateur de contexte"
      description="Assemblez un contexte pour une tâche et comprenez chaque inclusion et chaque exclusion."
      upcoming={["Paramètres : intention, budget de tokens, portées, fraîcheur, classification", "Cascade des étapes chronométrées de l'assemblage", "Éléments retenus avec citations et éléments exclus avec leur motif"]}
    />
  );
}
