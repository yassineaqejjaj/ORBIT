import type { Tone } from "@/lib/enums";
import type {
  ConnectorConfig,
  ConnectorRunStatus,
  ConnectorRunTrigger,
  ConnectorStatus,
  ConnectorType,
  NativeConnectorType,
  PresetField,
} from "@/lib/api/features-connectors";

export interface CredentialField {
  key: keyof ConnectorConfig | "secret";
  label: string;
  placeholder?: string;
  hint?: string;
  type?: "text" | "email" | "url" | "password";
  required?: boolean;
  /** Only shown for this deployment (Confluence / Jira). */
  deployment?: "cloud" | "datacenter";
}

export interface ConnectorTypeMeta {
  type: NativeConnectorType;
  label: string;
  tagline: string;
  description: string;
  sourceKind: "document" | "ticket";
  hasDeployment: boolean;
  fields: CredentialField[];
  scopeLabel: string;
}

export const CONNECTOR_TYPES: Record<NativeConnectorType, ConnectorTypeMeta> = {
  sharepoint: {
    type: "sharepoint",
    label: "SharePoint / OneDrive",
    tagline: "Bibliothèques de documents Microsoft 365",
    description:
      "Application Microsoft Entra (client credentials) avec la permission Sites.Read.All. Synchronisation incrémentale par delta query.",
    sourceKind: "document",
    hasDeployment: false,
    scopeLabel: "Sites et bibliothèques",
    fields: [
      { key: "tenant_id", label: "Identifiant du locataire (tenant)", placeholder: "00000000-0000-0000-0000-000000000000", required: true },
      { key: "client_id", label: "Identifiant de l'application (client)", placeholder: "00000000-0000-0000-0000-000000000000", required: true },
      { key: "secret", label: "Secret client", type: "password", required: true, hint: "Chiffré au repos, jamais réaffiché." },
    ],
  },
  confluence: {
    type: "confluence",
    label: "Confluence",
    tagline: "Pages des espaces Cloud ou Data Center",
    description: "E-mail + jeton d'API (Cloud) ou jeton d'accès personnel (Data Center). Incrémental via CQL lastmodified.",
    sourceKind: "document",
    hasDeployment: true,
    scopeLabel: "Espaces",
    fields: [
      { key: "base_url", label: "URL du site", type: "url", placeholder: "https://exemple.atlassian.net/wiki", required: true },
      { key: "email", label: "E-mail du compte", type: "email", placeholder: "robot@exemple.fr", required: true, deployment: "cloud" },
      { key: "secret", label: "Jeton d'API / jeton d'accès personnel", type: "password", required: true, hint: "Chiffré au repos, jamais réaffiché." },
    ],
  },
  jira: {
    type: "jira",
    label: "Jira",
    tagline: "Tickets et commentaires, filtrés par JQL",
    description: "Chaque ticket devient un document « ticket » (clé = identifiant externe), commentaires inclus.",
    sourceKind: "ticket",
    hasDeployment: true,
    scopeLabel: "Requête JQL",
    fields: [
      { key: "base_url", label: "URL de Jira", type: "url", placeholder: "https://exemple.atlassian.net", required: true },
      { key: "email", label: "E-mail du compte", type: "email", placeholder: "robot@exemple.fr", required: true, deployment: "cloud" },
      { key: "secret", label: "Jeton d'API / jeton d'accès personnel", type: "password", required: true, hint: "Chiffré au repos, jamais réaffiché." },
    ],
  },
};

export const CONNECTOR_TYPE_ORDER: NativeConnectorType[] = ["sharepoint", "confluence", "jira"];

export function isNativeType(type: ConnectorType): type is NativeConnectorType {
  return type !== "mcp";
}

/** Label of the scope row (detail sheet, edit dialog). */
export function scopeLabelFor(type: ConnectorType): string {
  return isNativeType(type) ? CONNECTOR_TYPES[type].scopeLabel : "Périmètre";
}

/* --- MCP presets (F6) ----------------------------------------------------------------------------------- */

/** Scope keys of the MCP presets, summarised in lists and the detail sheet. */
const MCP_SCOPE_KEYS = ["space_keys", "jql", "drive_ids", "folder_ids", "channels", "repos", "folders", "team", "project"];

/** Whether a preset field is shown for the current values (``visible_if: "field=value"``). */
export function presetFieldVisible(field: PresetField, values: Record<string, unknown>): boolean {
  if (!field.visible_if) return true;
  const [key = "", expected = ""] = field.visible_if.split("=");
  return String(values[key] ?? "") === expected;
}

/** Initial values of a preset's non-secret fields (defaults from the API). */
export function presetDefaults(fields: PresetField[]): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const field of fields) {
    if (field.group === "secret") continue;
    if (field.default !== null && field.default !== undefined) values[field.key] = field.default;
    else if (field.kind === "bool") values[field.key] = false;
    else if (field.kind === "list") values[field.key] = [];
  }
  return values;
}

/** Whether every visible required field of ``groups`` is filled. */
export function presetFieldsFilled(
  fields: PresetField[],
  groups: PresetField["group"][],
  values: Record<string, unknown>,
  secrets: Record<string, string>,
): boolean {
  return fields
    .filter((f) => groups.includes(f.group) && f.required && presetFieldVisible(f, values))
    .every((f) => {
      const value = f.group === "secret" ? secrets[f.key] : values[f.key];
      if (Array.isArray(value)) return value.length > 0;
      return value !== undefined && value !== null && String(value).trim() !== "";
    });
}

export const CONNECTOR_STATUS_META: Record<ConnectorStatus, { label: string; tone: Tone }> = {
  idle: { label: "Jamais synchronisé", tone: "neutral" },
  syncing: { label: "Synchronisation…", tone: "blue" },
  ok: { label: "À jour", tone: "green" },
  error: { label: "En erreur", tone: "red" },
  paused: { label: "En pause", tone: "amber" },
};

export const RUN_STATUS_META: Record<ConnectorRunStatus, { label: string; tone: Tone }> = {
  queued: { label: "En attente", tone: "neutral" },
  running: { label: "En cours", tone: "blue" },
  succeeded: { label: "Réussie", tone: "green" },
  partial: { label: "Partielle", tone: "amber" },
  failed: { label: "Échec", tone: "red" },
};

export const RUN_TRIGGER_LABELS: Record<ConnectorRunTrigger, string> = {
  manual: "Manuelle",
  schedule: "Planifiée",
  initial: "Initiale",
};

export const SCHEDULE_OPTIONS = [
  { value: "0", label: "Manuelle uniquement" },
  { value: "15", label: "Toutes les 15 minutes" },
  { value: "60", label: "Toutes les heures" },
  { value: "360", label: "Toutes les 6 heures" },
  { value: "1440", label: "Une fois par jour" },
] as const;

export function scheduleLabel(minutes: number): string {
  const option = SCHEDULE_OPTIONS.find((o) => Number(o.value) === minutes);
  if (option) return option.label;
  if (minutes % 60 === 0) return `Toutes les ${minutes / 60} heures`;
  return `Toutes les ${minutes} minutes`;
}

/** Human summary of the configured scope. */
export function scopeSummary(type: ConnectorType, config: ConnectorConfig): string {
  if (config.scope_labels?.length) return config.scope_labels.join(", ");
  if (type === "mcp") {
    const parts = MCP_SCOPE_KEYS.flatMap((key) => {
      const value = config[key];
      if (Array.isArray(value)) return value.map(String);
      return typeof value === "string" && value ? [value] : [];
    });
    return parts.length ? parts.slice(0, 6).join(", ") + (parts.length > 6 ? "…" : "") : "Tout le contenu accessible";
  }
  if (type === "jira") return config.jql ?? "—";
  if (type === "confluence") return (config.space_keys ?? []).join(", ") || "—";
  const count = (config.drive_ids?.length ?? 0) || (config.site_ids?.length ?? 0);
  return count ? `${count} élément(s) sélectionné(s)` : "—";
}
