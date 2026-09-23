import type { Metadata } from "next";
import { FileText } from "lucide-react";

import { UnderConstruction } from "@/components/layout/under-construction";

export const metadata: Metadata = { title: "Document" };

export default function DocumentPage() {
  return (
    <UnderConstruction
      icon={<FileText />}
      title="Document"
      description="Détail d'un document : versions, extraits, données personnelles détectées, jobs et mémoire dérivée."
      upcoming={["Extraits de la version courante avec caviardage", "Historique des versions et des traitements", "Réindexation, reclassification et oubli sélectif"]}
    />
  );
}
