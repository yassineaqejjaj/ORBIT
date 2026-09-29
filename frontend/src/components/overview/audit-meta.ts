/**
 * French labels, tones and grouping for audit actions (backend `app/services/audit.py`, `<domain>.<verb>`).
 * Shared by the overview activity timeline and the settings audit table.
 */
import type { Tone } from "@/lib/enums";

export interface AuditActionMeta {
  label: string;
  tone: Tone;
}

export const AUDIT_ACTION_META: Record<string, AuditActionMeta> = {
  "auth.login": { label: "Connexion", tone: "neutral" },
  "auth.login_failed": { label: "Connexion refusée", tone: "red" },
  "auth.logout": { label: "Déconnexion", tone: "neutral" },
  "user.create": { label: "Utilisateur créé", tone: "blue" },
  "user.update": { label: "Utilisateur modifié", tone: "blue" },
  "project.create": { label: "Projet créé", tone: "teal" },
  "project.update": { label: "Paramètres modifiés", tone: "teal" },
  "member.add": { label: "Membre ajouté", tone: "violet" },
  "member.update": { label: "Rôle modifié", tone: "violet" },
  "member.remove": { label: "Membre retiré", tone: "violet" },
  "agent.create": { label: "Agent créé", tone: "sky" },
  "agent.rotate": { label: "Clé d'agent renouvelée", tone: "sky" },
  "agent.revoke": { label: "Agent révoqué", tone: "red" },
  "source.create": { label: "Source créée", tone: "blue" },
  "source.update": { label: "Source modifiée", tone: "blue" },
  "document.ingest": { label: "Document ingéré", tone: "blue" },
  "document.import": { label: "Import de données", tone: "blue" },
  "document.update": { label: "Document modifié", tone: "blue" },
  "document.reprocess": { label: "Retraitement", tone: "sky" },
  "document.forget": { label: "Oubli sélectif", tone: "red" },
  "document.indexed": { label: "Document indexé", tone: "green" },
  "document.failed": { label: "Échec d'ingestion", tone: "red" },
  "memory.create": { label: "Mémoire créée", tone: "teal" },
  "memory.edit": { label: "Mémoire modifiée", tone: "teal" },
  "memory.validate": { label: "Mémoire validée", tone: "green" },
  "memory.obsolete": { label: "Marquée obsolète", tone: "neutral" },
  "memory.supersede": { label: "Mémoire remplacée", tone: "amber" },
  "memory.restore": { label: "Mémoire restaurée", tone: "teal" },
  "memory.forget": { label: "Mémoire oubliée", tone: "red" },
  "memory.conflict": { label: "Conflit détecté", tone: "orange" },
  "memory.consolidate": { label: "Consolidation", tone: "violet" },
  "session.close": { label: "Session clôturée", tone: "sky" },
  "context.request": { label: "Contexte servi", tone: "orange" },
  "context.feedback": { label: "Retour sur un contexte", tone: "orange" },
  "snapshot.create": { label: "Snapshot enregistré", tone: "violet" },
  "governance.acl_change": { label: "Droits d'accès modifiés", tone: "amber" },
  "governance.classification_change": { label: "Classification modifiée", tone: "amber" },
  "traces.export": { label: "Export des traces", tone: "neutral" },
};

/** Action domains usable as an audit filter (the API matches every verb of a domain). */
export const AUDIT_DOMAINS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "document", label: "Documents & ingestion" },
  { value: "memory", label: "Mémoire" },
  { value: "context", label: "Contextes servis" },
  { value: "snapshot", label: "Snapshots" },
  { value: "governance", label: "Gouvernance (ACL, classification)" },
  { value: "source", label: "Sources" },
  { value: "agent", label: "Agents & clés API" },
  { value: "member", label: "Membres" },
  { value: "project", label: "Projet" },
  { value: "session", label: "Sessions d'agents" },
  { value: "auth", label: "Connexions" },
  { value: "traces", label: "Exports de traces" },
];

const DOMAIN_TONES: Record<string, Tone> = {
  document: "blue",
  memory: "teal",
  context: "orange",
  snapshot: "violet",
  governance: "amber",
  source: "blue",
  agent: "sky",
  member: "violet",
  project: "teal",
  session: "sky",
  auth: "neutral",
  traces: "neutral",
};

/** Meta for any action string, with a readable fallback for unknown actions. */
export function auditActionMeta(action: string): AuditActionMeta {
  const known = AUDIT_ACTION_META[action];
  if (known) return known;
  const [domain = "", verb = ""] = action.split(".");
  const domainLabel = AUDIT_DOMAINS.find((d) => d.value === domain)?.label;
  return {
    label: domainLabel ? `${domainLabel}${verb ? ` · ${verb}` : ""}` : action || "Action",
    tone: DOMAIN_TONES[domain] ?? "neutral",
  };
}

/** French label of an audit target type. */
export function auditTargetLabel(targetType: string | null | undefined): string {
  switch (targetType) {
    case "document":
      return "Document";
    case "memory":
      return "Mémoire";
    case "chunk":
      return "Extrait";
    case "source":
      return "Source";
    case "agent":
      return "Agent";
    case "user":
    case "member":
      return "Membre";
    case "project":
      return "Projet";
    case "context_request":
    case "context":
      return "Contexte";
    case "snapshot":
      return "Snapshot";
    case "session":
      return "Session";
    case "job":
      return "Traitement";
    default:
      return targetType ? targetType : "—";
  }
}
