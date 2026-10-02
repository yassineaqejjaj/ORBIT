import { projectHref } from "@/components/layout/nav";
import { normalizeText } from "@/lib/utils";

export interface AlertLink {
  href: string;
  /** Accessible, descriptive label. */
  label: string;
  /** Short call to action shown in the attention list. */
  cta: string;
}

/** Best-effort link from a backend alert message to the screen where it can be handled. */
export function alertLink(slug: string, message: string): AlertLink | null {
  const text = normalizeText(message);
  if (/(echec|echoue|failed|erreur)/.test(text)) {
    return { href: `${projectHref(slug, "sources")}?tab=jobs&job_status=failed`, label: "Voir les traitements en échec", cta: "Voir" };
  }
  if (/(conflit|contradi)/.test(text)) {
    return { href: `${projectHref(slug, "inbox")}?tab=conflicts`, label: "Arbitrer les contradictions", cta: "Arbitrer" };
  }
  if (/(propos|a valider|en attente de validation)/.test(text)) {
    return { href: projectHref(slug, "inbox"), label: "Revoir les propositions", cta: "Revoir" };
  }
  if (/\bc3\b|secret/.test(text)) {
    return { href: `${projectHref(slug, "sources")}?classification=3`, label: "Voir les documents C3", cta: "Voir" };
  }
  if (/\bc2\b|confidentiel|classifi/.test(text)) {
    return { href: `${projectHref(slug, "sources")}?classification=2`, label: "Voir les documents C2", cta: "Voir" };
  }
  if (/(donnees personnelles|pii)/.test(text)) {
    return { href: projectHref(slug, "sources"), label: "Voir les sources", cta: "Voir" };
  }
  if (/(perime|fraicheur|obsolete)/.test(text)) {
    return { href: `${projectHref(slug, "settings")}?tab=project`, label: "Politiques de fraîcheur", cta: "Régler" };
  }
  if (/(en attente|en cours|file)/.test(text)) {
    return { href: `${projectHref(slug, "sources")}?tab=jobs`, label: "Suivre l'ingestion", cta: "Suivre" };
  }
  return null;
}
