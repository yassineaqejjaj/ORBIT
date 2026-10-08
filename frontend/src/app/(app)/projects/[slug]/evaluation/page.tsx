import type { Metadata } from "next";

import { EvaluationView } from "@/components/evaluation/evaluation-view";

export const metadata: Metadata = { title: "Évaluation" };

export default function EvaluationPage() {
  return <EvaluationView />;
}
