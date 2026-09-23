import type { Metadata } from "next";
import { Settings } from "lucide-react";

import { UnderConstruction } from "@/components/layout/under-construction";

export const metadata: Metadata = { title: "Paramètres" };

export default function SettingsPage() {
  return (
    <UnderConstruction
      icon={<Settings />}
      title="Paramètres"
      description="Configuration du projet, membres, agents et politiques de fraîcheur et de pertinence."
      upcoming={["Membres et rôles (propriétaire, éditeur, lecteur)", "Agents et clés API (création, rotation, révocation)", "Politiques : fraîcheur par type de source, budget de tokens, seuil de pertinence"]}
    />
  );
}
