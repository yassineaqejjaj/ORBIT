import type { Metadata } from "next";
import { LayoutDashboard } from "lucide-react";

import { UnderConstruction } from "@/components/layout/under-construction";

export const metadata: Metadata = { title: "Vue projet" };

export default function ProjectOverviewPage() {
  return (
    <UnderConstruction
      icon={<LayoutDashboard />}
      title="Vue projet"
      description="Indicateurs clés, décisions en vigueur, alertes de gouvernance et activité récente du projet."
      upcoming={["Statistiques : sources, documents indexés, mémoire, contextes servis", "Dernières décisions validées et alertes (jobs en échec, conflits, contenus C3)", "Journal d'audit des actions récentes"]}
    />
  );
}
