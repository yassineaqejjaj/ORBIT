import type { Metadata } from "next";
import { Database } from "lucide-react";

import { UnderConstruction } from "@/components/layout/under-construction";

export const metadata: Metadata = { title: "Sources" };

export default function SourcesPage() {
  return (
    <UnderConstruction
      icon={<Database />}
      title="Sources"
      description="Sources métier connectées, documents ingérés et suivi du pipeline d'ingestion."
      upcoming={["Import de fichiers (PDF, DOCX, Markdown, HTML), de texte et de lots JSON/CSV", "Suivi des étapes : extraction, données personnelles, classification, découpage, vectorisation, indexation", "Filtres par statut, type de source et classification"]}
    />
  );
}
