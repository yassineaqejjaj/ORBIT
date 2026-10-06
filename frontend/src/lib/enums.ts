/**
 * ORBIT enums — mirror of backend `app/enums.py` (docs/ARCHITECTURE.md §4).
 * Values MUST stay identical to the backend. Each enum exposes:
 *   - a string-union type,
 *   - a `const` array of values (ordered for display),
 *   - a `*_META` record with the French label, a color tone and (when relevant) a lucide icon name.
 */

/* -------------------------------------------------------------------------- */
/* Shared meta types                                                          */
/* -------------------------------------------------------------------------- */

/** Semantic color tones, rendered by <Badge tone=…>, <ScoreBar tone=…>, etc. */
export const TONES = [
  "neutral",
  "teal",
  "green",
  "amber",
  "red",
  "blue",
  "sky",
  "violet",
  "orange",
  "pink",
] as const;
export type Tone = (typeof TONES)[number];

/**
 * Lucide icon names used by enum metadata. Resolved to components by
 * `src/components/domain/enum-icon.tsx` (keeps this module free of React).
 */
export type IconName =
  | "FileText"
  | "StickyNote"
  | "Ticket"
  | "Building2"
  | "MessageSquareQuote"
  | "Bot"
  | "Globe"
  | "Timer"
  | "FolderKanban"
  | "UserRound"
  | "Landmark"
  | "Gavel"
  | "ListChecks"
  | "ShieldAlert"
  | "BookOpen"
  | "Heart"
  | "ScrollText"
  | "TriangleAlert"
  | "Package"
  | "Palette"
  | "CodeXml"
  | "FlaskConical"
  | "Wrench"
  | "Crown"
  | "PencilLine"
  | "Eye"
  | "Layers"
  | "Brain"
  | "MessagesSquare";

export interface EnumMeta {
  /** French UI label. */
  label: string;
  /** Color tone token. */
  tone: Tone;
  /** Optional lucide icon name. */
  icon?: IconName;
  /** Optional longer French description (tooltips, help text). */
  description?: string;
}

/** Safe lookup for values that may be unknown to this frontend version. */
export function getMeta<K extends string>(
  meta: Record<K, EnumMeta>,
  value: string | null | undefined,
): EnumMeta {
  if (value && Object.prototype.hasOwnProperty.call(meta, value)) {
    return meta[value as K];
  }
  return { label: value ?? "—", tone: "neutral" };
}

/** Type guard helper for enum values coming from untyped sources (URL params…). */
export function isEnumValue<T extends string>(values: readonly T[], value: unknown): value is T {
  return typeof value === "string" && (values as readonly string[]).includes(value);
}

/* -------------------------------------------------------------------------- */
/* Role                                                                       */
/* -------------------------------------------------------------------------- */

export const ROLES = ["owner", "editor", "viewer"] as const;
export type Role = (typeof ROLES)[number];

export const ROLE_META: Record<Role, EnumMeta> = {
  owner: {
    label: "Propriétaire",
    tone: "violet",
    icon: "Crown",
    description: "Gère les membres, les agents, les paramètres et l'oubli sélectif.",
  },
  editor: {
    label: "Éditeur",
    tone: "blue",
    icon: "PencilLine",
    description: "Ingère des sources, gère la mémoire et lance des contextes.",
  },
  viewer: {
    label: "Lecteur",
    tone: "neutral",
    icon: "Eye",
    description: "Lecture seule et accès à l'explorateur de contexte.",
  },
};

/** Numeric rank for role comparison (owner ⊃ editor ⊃ viewer). */
export const ROLE_RANK: Record<Role, number> = { viewer: 1, editor: 2, owner: 3 };

/** True when `role` is at least `min`. */
export function hasMinRole(role: Role | null | undefined, min: Role): boolean {
  if (!role) return false;
  return ROLE_RANK[role] >= ROLE_RANK[min];
}

/* -------------------------------------------------------------------------- */
/* SourceKind                                                                 */
/* -------------------------------------------------------------------------- */

export const SOURCE_KINDS = [
  "document",
  "note",
  "ticket",
  "crm",
  "feedback",
  "agent_trace",
  "url",
] as const;
export type SourceKind = (typeof SOURCE_KINDS)[number];

export const SOURCE_KIND_META: Record<SourceKind, EnumMeta & { icon: IconName }> = {
  document: { label: "Document", tone: "blue", icon: "FileText", description: "PDF, DOCX, Markdown, HTML, texte" },
  note: { label: "Note", tone: "amber", icon: "StickyNote", description: "Notes et comptes rendus" },
  ticket: { label: "Ticket", tone: "orange", icon: "Ticket", description: "Tickets (Jira, ServiceNow…)" },
  crm: { label: "CRM", tone: "violet", icon: "Building2", description: "Comptes et opportunités CRM" },
  feedback: { label: "Retour utilisateur", tone: "pink", icon: "MessageSquareQuote", description: "Verbatims et retours clients" },
  agent_trace: { label: "Trace d'agent", tone: "sky", icon: "Bot", description: "Traces d'exécution d'agents IA" },
  url: { label: "Page web", tone: "teal", icon: "Globe", description: "Pages web et liens" },
};

/* -------------------------------------------------------------------------- */
/* DocumentStatus / ChunkStatus                                               */
/* -------------------------------------------------------------------------- */

export const DOCUMENT_STATUSES = ["pending", "processing", "indexed", "failed", "forgotten"] as const;
export type DocumentStatus = (typeof DOCUMENT_STATUSES)[number];

export const DOCUMENT_STATUS_META: Record<DocumentStatus, EnumMeta> = {
  pending: { label: "En attente", tone: "neutral", description: "En attente de traitement par le pipeline" },
  processing: { label: "En traitement", tone: "blue", description: "Extraction, classification et indexation en cours" },
  indexed: { label: "Indexé", tone: "green", description: "Disponible pour la recherche et l'assemblage de contexte" },
  failed: { label: "En échec", tone: "red", description: "Le traitement a échoué" },
  forgotten: { label: "Oublié", tone: "neutral", description: "Oubli sélectif : retiré des index" },
};

export const CHUNK_STATUSES = ["active", "superseded", "forgotten"] as const;
export type ChunkStatus = (typeof CHUNK_STATUSES)[number];

export const CHUNK_STATUS_META: Record<ChunkStatus, EnumMeta> = {
  active: { label: "Actif", tone: "green" },
  superseded: { label: "Remplacé", tone: "amber" },
  forgotten: { label: "Oublié", tone: "neutral" },
};

/* -------------------------------------------------------------------------- */
/* Jobs                                                                       */
/* -------------------------------------------------------------------------- */

export const JOB_KINDS = ["ingest", "reindex", "forget", "consolidate", "extract_memory"] as const;
export type JobKind = (typeof JOB_KINDS)[number];

export const JOB_KIND_META: Record<JobKind, EnumMeta> = {
  ingest: { label: "Ingestion", tone: "blue" },
  reindex: { label: "Réindexation", tone: "sky" },
  forget: { label: "Oubli", tone: "red" },
  consolidate: { label: "Consolidation", tone: "violet" },
  extract_memory: { label: "Extraction mémoire", tone: "teal" },
};

export const JOB_STATUSES = ["queued", "running", "succeeded", "failed"] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];

export const JOB_STATUS_META: Record<JobStatus, EnumMeta> = {
  queued: { label: "En file", tone: "neutral" },
  running: { label: "En cours", tone: "blue" },
  succeeded: { label: "Réussi", tone: "green" },
  failed: { label: "Échec", tone: "red" },
};

/** Canonical ingestion pipeline steps (ARCHITECTURE §7). */
export const JOB_STEP_NAMES = [
  "extract",
  "pii",
  "classify",
  "visual",
  "chunk",
  "contextualize",
  "embed",
  "index",
  "extract_memory",
] as const;
/** Steps recorded only for some documents (images present). */
export const OPTIONAL_JOB_STEPS: ReadonlySet<string> = new Set(["visual"]);
export type JobStepName = (typeof JOB_STEP_NAMES)[number];

export const JOB_STEP_META: Record<JobStepName, EnumMeta> = {
  extract: { label: "Extraction", tone: "blue", description: "Extraction et normalisation du texte" },
  pii: { label: "Données personnelles", tone: "pink", description: "Détection et caviardage des données personnelles" },
  classify: { label: "Classification", tone: "amber", description: "Niveau de classification C0–C3" },
  visual: { label: "Éléments visuels", tone: "orange", description: "Images des PDF/PPTX décrites (LLM vision, OCR ou texte alternatif)" },
  chunk: { label: "Découpage", tone: "sky", description: "Découpage structurel en extraits" },
  contextualize: { label: "Contextualisation", tone: "teal", description: "Préambule contextuel de chaque extrait (LLM ou déterministe)" },
  embed: { label: "Vectorisation", tone: "violet", description: "Calcul des embeddings" },
  index: { label: "Indexation", tone: "teal", description: "Indexation OpenSearch (BM25 + k-NN)" },
  extract_memory: { label: "Extraction mémoire", tone: "green", description: "Décisions, besoins, contraintes, risques, faits" },
};

export const JOB_STEP_STATUSES = ["ok", "failed", "skipped"] as const;
export type JobStepStatus = (typeof JOB_STEP_STATUSES)[number];

export const JOB_STEP_STATUS_META: Record<JobStepStatus, EnumMeta> = {
  ok: { label: "OK", tone: "green" },
  failed: { label: "Échec", tone: "red" },
  skipped: { label: "Ignoré", tone: "neutral" },
};

/* -------------------------------------------------------------------------- */
/* Memory                                                                     */
/* -------------------------------------------------------------------------- */

export const MEMORY_SCOPES = ["short_term", "project", "user", "long_term"] as const;
export type MemoryScope = (typeof MEMORY_SCOPES)[number];

export const MEMORY_SCOPE_META: Record<MemoryScope, EnumMeta> = {
  short_term: {
    label: "Court terme",
    tone: "sky",
    icon: "Timer",
    description: "Tours de session d'un agent, expirent automatiquement",
  },
  project: {
    label: "Projet",
    tone: "teal",
    icon: "FolderKanban",
    description: "Décisions, besoins, contraintes, risques et faits du projet",
  },
  user: {
    label: "Utilisateur",
    tone: "violet",
    icon: "UserRound",
    description: "Préférences personnelles, visibles du seul utilisateur concerné",
  },
  long_term: {
    label: "Long terme",
    tone: "blue",
    icon: "Landmark",
    description: "Faits consolidés et durables",
  },
};

export const MEMORY_KINDS = [
  "decision",
  "requirement",
  "constraint",
  "fact",
  "preference",
  "summary",
  "risk",
] as const;
export type MemoryKind = (typeof MEMORY_KINDS)[number];

export const MEMORY_KIND_META: Record<MemoryKind, EnumMeta & { icon: IconName }> = {
  decision: { label: "Décision", tone: "teal", icon: "Gavel" },
  requirement: { label: "Besoin", tone: "blue", icon: "ListChecks" },
  constraint: { label: "Contrainte", tone: "orange", icon: "ShieldAlert" },
  fact: { label: "Fait", tone: "neutral", icon: "BookOpen" },
  preference: { label: "Préférence", tone: "violet", icon: "Heart" },
  summary: { label: "Synthèse", tone: "sky", icon: "ScrollText" },
  risk: { label: "Risque", tone: "red", icon: "TriangleAlert" },
};

export const MEMORY_STATUSES = ["proposed", "validated", "superseded", "obsolete", "forgotten"] as const;
export type MemoryStatus = (typeof MEMORY_STATUSES)[number];

export const MEMORY_STATUS_META: Record<MemoryStatus, EnumMeta> = {
  proposed: { label: "Proposé", tone: "amber", description: "En attente de validation humaine" },
  validated: { label: "Validé", tone: "green", description: "Validé, servi en priorité aux agents" },
  superseded: { label: "Remplacé", tone: "neutral", description: "Remplacé par une version plus récente" },
  obsolete: { label: "Obsolète", tone: "neutral", description: "N'est plus en vigueur" },
  forgotten: { label: "Oublié", tone: "red", description: "Oubli sélectif : contenu effacé" },
};

export const MEMORY_EVENT_TYPES = [
  "created",
  "edited",
  "validated",
  "superseded",
  "obsoleted",
  "forgotten",
  "restored",
  "conflict_detected",
] as const;
export type MemoryEventType = (typeof MEMORY_EVENT_TYPES)[number];

export const MEMORY_EVENT_META: Record<MemoryEventType, EnumMeta> = {
  created: { label: "Création", tone: "blue" },
  edited: { label: "Modification", tone: "sky" },
  validated: { label: "Validation", tone: "green" },
  superseded: { label: "Remplacement", tone: "amber" },
  obsoleted: { label: "Obsolescence", tone: "neutral" },
  forgotten: { label: "Oubli", tone: "red" },
  restored: { label: "Restauration", tone: "teal" },
  conflict_detected: { label: "Conflit détecté", tone: "orange" },
};

export const RELATION_TYPES = [
  "supersedes",
  "contradicts",
  "derived_from",
  "mentions",
  "constrains",
  "relates_to",
] as const;
export type RelationType = (typeof RELATION_TYPES)[number];

export const RELATION_TYPE_META: Record<RelationType, EnumMeta> = {
  supersedes: { label: "Remplace", tone: "amber" },
  contradicts: { label: "Contredit", tone: "red" },
  derived_from: { label: "Dérivé de", tone: "blue" },
  mentions: { label: "Mentionne", tone: "neutral" },
  constrains: { label: "Contraint", tone: "orange" },
  relates_to: { label: "Lié à", tone: "sky" },
};

/** Node types that can appear on either end of a relation. */
export const RELATION_NODE_TYPES = ["chunk", "memory", "document"] as const;
export type RelationNodeType = (typeof RELATION_NODE_TYPES)[number];

/* -------------------------------------------------------------------------- */
/* Context assembly                                                           */
/* -------------------------------------------------------------------------- */

export const CANDIDATE_TYPES = ["chunk", "memory", "session"] as const;
export type CandidateType = (typeof CANDIDATE_TYPES)[number];

export const CANDIDATE_TYPE_META: Record<CandidateType, EnumMeta> = {
  chunk: { label: "Extrait de source", tone: "blue", icon: "Layers" },
  memory: { label: "Mémoire", tone: "teal", icon: "Brain" },
  session: { label: "Session", tone: "sky", icon: "MessagesSquare" },
};

export const INTENTS = [
  "general",
  "specification",
  "design",
  "engineering",
  "research",
  "analysis",
  "validation",
] as const;
export type Intent = (typeof INTENTS)[number];

export const INTENT_META: Record<Intent, EnumMeta> = {
  general: { label: "Général", tone: "neutral" },
  specification: { label: "Spécification", tone: "blue" },
  design: { label: "Conception", tone: "violet" },
  engineering: { label: "Ingénierie", tone: "teal" },
  research: { label: "Recherche", tone: "sky" },
  analysis: { label: "Analyse", tone: "orange" },
  validation: { label: "Validation", tone: "green" },
};

export const REASON_CODES = [
  "INCLUDED_RELEVANT",
  "INCLUDED_PINNED",
  "EXCLUDED_ACL",
  "EXCLUDED_CLASSIFICATION",
  "EXCLUDED_SCOPE",
  "EXCLUDED_STALE",
  "EXCLUDED_EXPIRED",
  "EXCLUDED_SUPERSEDED",
  "EXCLUDED_CONFLICT",
  "EXCLUDED_DUPLICATE",
  "EXCLUDED_LOW_SCORE",
  "EXCLUDED_BUDGET",
  "EXCLUDED_FORGOTTEN",
  "EXCLUDED_QUARANTINE",
] as const;
export type ReasonCode = (typeof REASON_CODES)[number];

export type IncludedReasonCode = Extract<ReasonCode, `INCLUDED_${string}`>;
export type ExcludedReasonCode = Extract<ReasonCode, `EXCLUDED_${string}`>;

/** Reason code families: drive the badge tone and grouping in charts. */
export type ReasonGroup = "included" | "governance" | "quality" | "efficiency";

export const REASON_GROUP_META: Record<ReasonGroup, EnumMeta> = {
  included: { label: "Retenus", tone: "teal", description: "Éléments servis à l'agent" },
  governance: { label: "Gouvernance", tone: "red", description: "Droits d'accès, classification, oubli" },
  quality: { label: "Qualité", tone: "amber", description: "Péremption, remplacement, conflit, expiration" },
  efficiency: { label: "Efficacité", tone: "neutral", description: "Doublons, pertinence, budget, périmètre" },
};

export interface ReasonCodeMeta extends EnumMeta {
  /** Compact label for charts and dense tables. */
  short: string;
  group: ReasonGroup;
  included: boolean;
}

export const REASON_CODE_META: Record<ReasonCode, ReasonCodeMeta> = {
  INCLUDED_RELEVANT: { label: "Retenu — pertinent", short: "Pertinent", tone: "teal", group: "included", included: true },
  INCLUDED_PINNED: { label: "Retenu — hérité du snapshot", short: "Snapshot", tone: "green", group: "included", included: true },
  EXCLUDED_ACL: { label: "Exclu — accès non autorisé", short: "Accès", tone: "red", group: "governance", included: false },
  EXCLUDED_CLASSIFICATION: {
    label: "Exclu — classification trop élevée",
    short: "Classification",
    tone: "red",
    group: "governance",
    included: false,
  },
  EXCLUDED_FORGOTTEN: { label: "Exclu — oubli sélectif", short: "Oublié", tone: "red", group: "governance", included: false },
  EXCLUDED_QUARANTINE: {
    label: "Exclu — quarantaine (injection suspectée)",
    short: "Quarantaine",
    tone: "red",
    group: "governance",
    included: false,
  },
  EXCLUDED_STALE: { label: "Exclu — information périmée", short: "Périmé", tone: "amber", group: "quality", included: false },
  EXCLUDED_SUPERSEDED: { label: "Exclu — remplacé", short: "Remplacé", tone: "amber", group: "quality", included: false },
  EXCLUDED_CONFLICT: { label: "Exclu — contradiction résolue", short: "Conflit", tone: "amber", group: "quality", included: false },
  EXCLUDED_EXPIRED: {
    label: "Exclu — mémoire court terme expirée",
    short: "Expiré",
    tone: "amber",
    group: "quality",
    included: false,
  },
  EXCLUDED_DUPLICATE: { label: "Exclu — doublon", short: "Doublon", tone: "neutral", group: "efficiency", included: false },
  EXCLUDED_LOW_SCORE: {
    label: "Exclu — pertinence insuffisante",
    short: "Score faible",
    tone: "neutral",
    group: "efficiency",
    included: false,
  },
  EXCLUDED_BUDGET: { label: "Exclu — budget de tokens atteint", short: "Budget", tone: "neutral", group: "efficiency", included: false },
  EXCLUDED_SCOPE: { label: "Exclu — hors périmètre demandé", short: "Périmètre", tone: "neutral", group: "efficiency", included: false },
};

/** Governance evaluation order (ARCHITECTURE §9, step `govern`), then select-stage reasons. */
export const REASON_CODE_ORDER: readonly ReasonCode[] = [
  "INCLUDED_RELEVANT",
  "INCLUDED_PINNED",
  "EXCLUDED_FORGOTTEN",
  "EXCLUDED_ACL",
  "EXCLUDED_CLASSIFICATION",
  "EXCLUDED_QUARANTINE",
  "EXCLUDED_SCOPE",
  "EXCLUDED_EXPIRED",
  "EXCLUDED_STALE",
  "EXCLUDED_SUPERSEDED",
  "EXCLUDED_LOW_SCORE",
  "EXCLUDED_CONFLICT",
  "EXCLUDED_DUPLICATE",
  "EXCLUDED_BUDGET",
];

/** Context assembly stages, in execution order (ARCHITECTURE §9). */
export const CONTEXT_STAGES = [
  "understand",
  "rewrite",
  "retrieve",
  "fuse",
  "rerank",
  "govern",
  "select",
  "compress",
  "package",
] as const;
export type ContextStage = (typeof CONTEXT_STAGES)[number];

export const CONTEXT_STAGE_META: Record<ContextStage, EnumMeta> = {
  understand: { label: "Compréhension", tone: "sky", description: "Normalisation, intention, termes clés, embedding" },
  rewrite: { label: "Réécriture", tone: "violet", description: "Multi-requêtes, décomposition, HyDE ou expansion par synonymes et entités" },
  retrieve: { label: "Recherche", tone: "blue", description: "BM25 + k-NN sources et mémoire, session, snapshot — en 1 à 3 tours" },
  fuse: { label: "Fusion", tone: "violet", description: "Reciprocal Rank Fusion (k=60)" },
  rerank: { label: "Reclassement", tone: "pink", description: "Score combiné pertinence / fraîcheur / type" },
  govern: { label: "Gouvernance", tone: "red", description: "Oubli, ACL, classification, périmètre, fraîcheur…" },
  select: { label: "Sélection", tone: "amber", description: "Conflits, doublons, MMR, budget de tokens" },
  compress: { label: "Compression", tone: "orange", description: "Extraction des phrases clés, citations" },
  package: { label: "Assemblage", tone: "teal", description: "Markdown structuré et liste des sources" },
};

/* -------------------------------------------------------------------------- */
/* Agents                                                                     */
/* -------------------------------------------------------------------------- */

export const AGENT_KINDS = ["product", "design", "engineering", "research", "custom"] as const;
export type AgentKind = (typeof AGENT_KINDS)[number];

export const AGENT_KIND_META: Record<AgentKind, EnumMeta & { icon: IconName }> = {
  product: { label: "Produit", tone: "teal", icon: "Package" },
  design: { label: "Design", tone: "violet", icon: "Palette" },
  engineering: { label: "Ingénierie", tone: "blue", icon: "CodeXml" },
  research: { label: "Recherche", tone: "sky", icon: "FlaskConical" },
  custom: { label: "Personnalisé", tone: "neutral", icon: "Wrench" },
};

/* -------------------------------------------------------------------------- */
/* Classification (C0–C3)                                                     */
/* -------------------------------------------------------------------------- */

export const CLASSIFICATIONS = [0, 1, 2, 3] as const;
export type Classification = (typeof CLASSIFICATIONS)[number];

export interface ClassificationMeta extends EnumMeta {
  code: `C${Classification}`;
  /** True for levels that require the C2/C3 warning banner. */
  sensitive: boolean;
}

export const CLASSIFICATION_META: Record<Classification, ClassificationMeta> = {
  0: { code: "C0", label: "Public", tone: "neutral", sensitive: false, description: "Diffusable sans restriction" },
  1: { code: "C1", label: "Interne", tone: "blue", sensitive: false, description: "Réservé aux collaborateurs" },
  2: {
    code: "C2",
    label: "Confidentiel",
    tone: "amber",
    sensitive: true,
    description: "Diffusion restreinte aux personnes habilitées",
  },
  3: { code: "C3", label: "Secret", tone: "red", sensitive: true, description: "Accès strictement nominatif" },
};

/** Clamp any number to a valid classification level. */
export function toClassification(value: number | null | undefined): Classification {
  const n = Math.round(Number(value ?? 0));
  if (n <= 0 || Number.isNaN(n)) return 0;
  if (n >= 3) return 3;
  return n as Classification;
}

export function classificationCode(value: number | null | undefined): `C${Classification}` {
  return CLASSIFICATION_META[toClassification(value)].code;
}

export function isSensitiveClassification(value: number | null | undefined): boolean {
  return toClassification(value) >= 2;
}

/* -------------------------------------------------------------------------- */
/* Misc enums used in API payloads                                            */
/* -------------------------------------------------------------------------- */

export const PII_TYPES = ["EMAIL", "PHONE", "IBAN", "CARD", "NIR", "IP", "PERSON"] as const;
export type PiiType = (typeof PII_TYPES)[number];

export const PII_TYPE_META: Record<PiiType, EnumMeta> = {
  EMAIL: { label: "E-mail", tone: "blue" },
  PHONE: { label: "Téléphone", tone: "sky" },
  IBAN: { label: "IBAN", tone: "red" },
  CARD: { label: "Carte bancaire", tone: "red" },
  NIR: { label: "NIR", tone: "red", description: "Numéro d'inscription au répertoire" },
  IP: { label: "Adresse IP", tone: "neutral" },
  PERSON: { label: "Nom de personne", tone: "violet" },
};

export const ACTOR_TYPES = ["user", "agent", "system"] as const;
export type ActorType = (typeof ACTOR_TYPES)[number];

export const ACTOR_TYPE_META: Record<ActorType, EnumMeta> = {
  user: { label: "Utilisateur", tone: "blue", icon: "UserRound" },
  agent: { label: "Agent", tone: "teal", icon: "Bot" },
  system: { label: "Système", tone: "neutral", icon: "Wrench" },
};

export const ALERT_LEVELS = ["info", "warning", "critical"] as const;
export type AlertLevel = (typeof ALERT_LEVELS)[number];

export const ALERT_LEVEL_META: Record<AlertLevel, EnumMeta> = {
  info: { label: "Information", tone: "blue" },
  warning: { label: "Avertissement", tone: "amber" },
  critical: { label: "Critique", tone: "red" },
};

export const FEEDBACK_FLAGS = ["irrelevant", "outdated", "wrong"] as const;
export type FeedbackFlag = (typeof FEEDBACK_FLAGS)[number];

export const FEEDBACK_FLAG_META: Record<FeedbackFlag, EnumMeta> = {
  irrelevant: { label: "Non pertinent", tone: "neutral" },
  outdated: { label: "Obsolète", tone: "amber", description: "Crée une proposition d'obsolescence sur l'item mémoire" },
  wrong: { label: "Erroné", tone: "red" },
};

export const SESSION_TURN_ROLES = ["user", "agent", "tool"] as const;
export type SessionTurnRole = (typeof SESSION_TURN_ROLES)[number];

export const SESSION_TURN_ROLE_META: Record<SessionTurnRole, EnumMeta> = {
  user: { label: "Utilisateur", tone: "blue" },
  agent: { label: "Agent", tone: "teal" },
  tool: { label: "Outil", tone: "neutral" },
};

/** ACL principal helpers (ARCHITECTURE §3). */
export const ACL_ALL_MEMBERS = "project:*";
export const ACL_PRESETS = [
  { value: "project:*", label: "Tous les membres du projet" },
  { value: "role:editor", label: "Éditeurs et propriétaires" },
  { value: "role:owner", label: "Propriétaires uniquement" },
] as const;

/** Human label for an ACL principal (`user:<uuid>` falls back to a short id). */
export function aclPrincipalLabel(principal: string, userNames?: Record<string, string>): string {
  const preset = ACL_PRESETS.find((p) => p.value === principal);
  if (preset) return preset.label;
  if (principal.startsWith("user:")) {
    const id = principal.slice(5);
    return userNames?.[id] ?? `Utilisateur ${id.slice(0, 8)}`;
  }
  if (principal.startsWith("role:")) return `Rôle ${principal.slice(5)}`;
  return principal;
}

/* -------------------------------------------------------------------------- */
/* Source trust (AI security §A3)                                             */
/* -------------------------------------------------------------------------- */

export type SourceTrustLevel = "high" | "medium" | "low";

export const SOURCE_TRUST_META: Record<SourceTrustLevel, EnumMeta> = {
  high: { label: "Confiance élevée", tone: "teal", description: "Contenus maîtrisés : aucun ajustement du classement." },
  medium: { label: "Confiance moyenne", tone: "neutral", description: "Légère pénalité de classement." },
  low: {
    label: "Confiance faible",
    tone: "amber",
    description: "Pénalité de classement, jamais promu automatiquement en mémoire validée.",
  },
};

/** Default trust of each source kind (mirrors the backend `DEFAULT_SOURCE_TRUST`). */
export const DEFAULT_SOURCE_TRUST: Record<SourceKind, SourceTrustLevel> = {
  document: "high",
  note: "medium",
  ticket: "medium",
  crm: "medium",
  feedback: "low",
  agent_trace: "low",
  url: "low",
};
