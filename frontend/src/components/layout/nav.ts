import {
  Activity,
  Brain,
  Camera,
  Database,
  History,
  Inbox,
  MessageCircleQuestion,
  Plug,
  LayoutDashboard,
  Settings,
  Telescope,
  type LucideIcon,
} from "lucide-react";

import type { Role } from "@/lib/enums";

export interface ProjectNavItem {
  /** Path segment after /projects/[slug] ("" for the overview). */
  segment:
    | ""
    | "ask"
    | "inbox"
    | "changes"
    | "connectors"
    | "sources"
    | "memory"
    | "explorer"
    | "snapshots"
    | "observability"
    | "settings";
  label: string;
  icon: LucideIcon;
  description: string;
  /** Minimum role to show the entry (default viewer). */
  minRole?: Role;
  /** Command palette keywords. */
  keywords?: string[];
}

export const PROJECT_NAV: ProjectNavItem[] = [
  {
    segment: "",
    label: "Vue projet",
    icon: LayoutDashboard,
    description: "Indicateurs, décisions récentes, alertes et activité",
    keywords: ["accueil", "tableau de bord", "overview", "dashboard"],
  },
  {
    segment: "ask",
    label: "Demander à ORBIT",
    icon: MessageCircleQuestion,
    description: "Questions-réponses sur la mémoire du projet, avec citations",
    keywords: ["question", "chat", "assistant", "ask", "pourquoi"],
  },
  {
    segment: "inbox",
    label: "Tri de la mémoire",
    icon: Inbox,
    description: "Propositions à valider et contradictions à arbitrer",
    minRole: "editor",
    keywords: ["propositions", "validation", "conflits", "arbitrage", "triage"],
  },
  {
    segment: "changes",
    label: "Fil des changements",
    icon: History,
    description: "Ce qui a changé : décisions, remplacements, sources, snapshots",
    keywords: ["changements", "nouveautés", "abonnements", "webhooks", "digest"],
  },
  {
    segment: "connectors",
    label: "Connecteurs",
    icon: Plug,
    description: "SharePoint, Confluence, Jira : synchronisation automatique",
    minRole: "editor",
    keywords: ["sharepoint", "confluence", "jira", "synchronisation", "intégration"],
  },
  {
    segment: "sources",
    label: "Sources",
    icon: Database,
    description: "Sources métier, documents et pipeline d'ingestion",
    keywords: ["documents", "ingestion", "import", "upload"],
  },
  {
    segment: "memory",
    label: "Mémoire",
    icon: Brain,
    description: "Décisions, besoins, contraintes, faits et préférences",
    keywords: ["décisions", "memory", "graphe"],
  },
  {
    segment: "explorer",
    label: "Explorateur de contexte",
    icon: Telescope,
    description: "Assembler un contexte et comprendre chaque inclusion ou exclusion",
    keywords: ["contexte", "explorer", "agent", "requête"],
  },
  {
    segment: "snapshots",
    label: "Snapshots",
    icon: Camera,
    description: "Contextes partagés, versionnés et immuables",
    keywords: ["versions", "diff"],
  },
  {
    segment: "observability",
    label: "Observabilité",
    icon: Activity,
    description: "Latence, tokens, coûts, exclusions et traces",
    keywords: ["métriques", "metrics", "traces", "coût", "latence"],
  },
  {
    segment: "settings",
    label: "Paramètres",
    icon: Settings,
    description: "Projet, membres, agents et politiques",
    keywords: ["membres", "agents", "clés api", "configuration"],
  },
];

export function projectHref(slug: string, segment: ProjectNavItem["segment"] = ""): string {
  const base = `/projects/${encodeURIComponent(slug)}`;
  return segment ? `${base}/${segment}` : base;
}

/** Nav item matching the current pathname (overview only on exact match). */
export function activeProjectNav(pathname: string, slug: string): ProjectNavItem | undefined {
  const base = projectHref(slug);
  if (pathname === base || pathname === `${base}/`) return PROJECT_NAV[0];
  return PROJECT_NAV.find((item) => item.segment && pathname.startsWith(`${base}/${item.segment}`));
}
