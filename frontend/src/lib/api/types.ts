/**
 * ORBIT REST API v1 types — mirror of docs/API.md (names and fields exactly as written there).
 * Conventions: snake_case JSON, ISO 8601 UTC date strings, UUID strings.
 * Nullability follows the data model (docs/ARCHITECTURE.md §5): nullable DB columns are `T | null`.
 */
import type {
  ActorType,
  AgentKind,
  AlertLevel,
  CandidateType,
  Classification,
  DocumentStatus,
  FeedbackFlag,
  Intent,
  JobKind,
  JobStatus,
  JobStepStatus,
  MemoryEventType,
  MemoryKind,
  MemoryScope,
  MemoryStatus,
  PiiType,
  ReasonCode,
  RelationNodeType,
  RelationType,
  Role,
  SessionTurnRole,
  SourceKind,
  ChunkStatus,
} from "@/lib/enums";

/* -------------------------------------------------------------------------- */
/* Primitives                                                                 */
/* -------------------------------------------------------------------------- */

/** UUID v4 string. */
export type UUID = string;
/** ISO 8601 UTC date-time string. */
export type ISODateString = string;
/** Arbitrary JSON object. */
export type JsonObject = Record<string, unknown>;

/** Error body returned by the API for 4xx/5xx responses. */
export type ApiErrorCode = "not_found" | "forbidden" | "validation_error" | "conflict" | "unauthorized";
export interface ApiErrorBody {
  detail: string;
  code: ApiErrorCode | string;
}

/** Paginated collection. */
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface PageParams {
  /** 1-based, default 1. */
  page?: number;
  /** Default 25, max 100. */
  page_size?: number;
}

/* -------------------------------------------------------------------------- */
/* Shared types                                                               */
/* -------------------------------------------------------------------------- */

export interface User {
  id: UUID;
  email: string;
  full_name: string;
  is_admin: boolean;
  clearance: Classification;
  avatar_color: string;
  created_at: ISODateString;
}

export interface Member {
  user: User;
  role: Role;
  created_at: ISODateString;
}

export interface ProjectSettings {
  freshness_days: Record<SourceKind, number>;
  default_token_budget: number;
  min_relevance: number;
  short_term_ttl_hours: number;
}

export interface Project {
  id: UUID;
  slug: string;
  name: string;
  description: string | null;
  settings: ProjectSettings;
  /** Role of the caller in this project. */
  role: Role;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface ProjectStats {
  sources: number;
  documents: number;
  memory_items: number;
  context_requests_7d: number;
}

export type ProjectSummary = Project & { stats: ProjectStats };

export interface Agent {
  id: UUID;
  name: string;
  kind: AgentKind;
  description: string | null;
  clearance: Classification;
  api_key_prefix: string;
  active: boolean;
  created_at: ISODateString;
  last_used_at: ISODateString | null;
}

export interface AgentCreated {
  agent: Agent;
  /** Full API key — displayed only once. */
  api_key: string;
}

export interface SourceCounts {
  documents: number;
  indexed: number;
  failed: number;
  processing: number;
}

export interface Source {
  id: UUID;
  name: string;
  kind: SourceKind;
  description: string | null;
  default_classification: Classification;
  default_acl: string[];
  config: JsonObject;
  created_at: ISODateString;
  updated_at: ISODateString;
  last_ingested_at: ISODateString | null;
  /** Explicit trust (null = default of the kind) and effective level (AI security §A3). */
  trust?: SourceTrust | null;
  effective_trust?: SourceTrust;
  counts: SourceCounts;
}

export type SourceTrust = "high" | "medium" | "low";

/** One prompt-injection signal of a chunk (AI security §A1). */
export interface InjectionReason {
  code: string;
  label: string;
  weight: number;
  excerpt: string;
}

/** GET /projects/{slug}/documents/quarantine (owners). */
export interface QuarantinedChunk {
  id: UUID;
  document_id: UUID;
  document_title: string;
  version: number;
  ordinal: number;
  section: string | null;
  text: string;
  injection_score: number;
  injection_reasons: InjectionReason[];
  created_at: ISODateString;
}

export interface DocumentSummary {
  id: UUID;
  source_id: UUID;
  source_name: string;
  source_kind: SourceKind;
  external_id: string | null;
  title: string;
  uri: string | null;
  mime_type: string;
  author: string | null;
  classification: Classification;
  acl_principals: string[];
  tags: string[];
  status: DocumentStatus;
  status_reason: string | null;
  current_version: number;
  pii_count: number;
  chunk_count: number;
  source_updated_at: ISODateString | null;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface DocumentVersion {
  id: UUID;
  version: number;
  content_hash: string;
  size_bytes: number;
  created_at: ISODateString;
  char_count: number;
}

export interface PiiEntity {
  type: PiiType;
  start: number;
  end: number;
  /** Omitted when the caller is below `editor`. */
  text?: string;
}

export interface ChunkView {
  id: UUID;
  version: number;
  ordinal: number;
  text: string;
  text_redacted: string;
  token_count: number;
  section: string | null;
  pii: PiiEntity[];
  classification: Classification;
  status: ChunkStatus;
  injection_score?: number;
  injection_reasons?: InjectionReason[];
  quarantined?: boolean;
  quarantine_released_at?: ISODateString | null;
  /** Contextual-retrieval preamble indexed with the chunk (AI_CONTEXT_ENGINEERING §B1). */
  context_preamble?: string | null;
  context_source?: "llm" | "deterministic" | null;
}

/** Known pipeline step names; unknown names are allowed (`string`). */
export type JobStepNameValue =
  | "extract"
  | "pii"
  | "classify"
  | "visual"
  | "chunk"
  | "contextualize"
  | "embed"
  | "index"
  | "extract_memory"
  | (string & {});

export interface JobStep {
  name: JobStepNameValue;
  status: JobStepStatus;
  duration_ms: number | null;
  detail: string | null;
  /** Present in the stored step (ARCHITECTURE §5); optional in the API contract. */
  started_at?: ISODateString | null;
}

export interface Job {
  id: UUID;
  document_id: UUID | null;
  kind: JobKind;
  status: JobStatus;
  attempts: number;
  error: string | null;
  steps: JobStep[];
  created_at: ISODateString;
  started_at: ISODateString | null;
  finished_at: ISODateString | null;
}

/** Row of `GET /projects/{slug}/jobs`. */
export type JobWithDocument = Job & { document_title: string | null };

export type DocumentDetail = DocumentSummary & {
  metadata: JsonObject;
  versions: DocumentVersion[];
  /** Chunks of the current version. */
  chunks: ChunkView[];
  jobs: Job[];
  /** Derived memory items. */
  memory_items: MemoryItem[];
  forgotten_at: ISODateString | null;
  forgotten_by: string | null;
};

export interface MemoryItem {
  id: UUID;
  lineage_id: UUID;
  version: number;
  is_current: boolean;
  scope: MemoryScope;
  kind: MemoryKind;
  status: MemoryStatus;
  title: string;
  content: string;
  confidence: number;
  classification: Classification;
  acl_principals: string[];
  tags: string[];
  subject_user_id: UUID | null;
  session_id: string | null;
  expires_at: ISODateString | null;
  valid_from: ISODateString;
  valid_to: ISODateString | null;
  supersedes_id: UUID | null;
  superseded_by_id: UUID | null;
  created_by_type: ActorType;
  created_by_id: UUID | null;
  created_by_label: string | null;
  provenance_count: number;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface Provenance {
  id: UUID;
  document_id: UUID | null;
  document_title: string | null;
  chunk_id: UUID | null;
  context_request_id: UUID | null;
  source_label: string;
  excerpt: string;
  created_at: ISODateString;
}

export interface MemoryEvent {
  id: UUID;
  memory_item_id: UUID;
  event: MemoryEventType;
  actor_type: ActorType;
  actor_id: UUID | null;
  actor_label: string | null;
  reason: string | null;
  data: JsonObject;
  created_at: ISODateString;
}

export interface Relation {
  id: UUID;
  rel_type: RelationType;
  direction: "out" | "in";
  other_type: RelationNodeType;
  other_id: UUID;
  other_title: string | null;
  confidence: number;
  detail: string | null;
  created_at: ISODateString;
}

export interface MemoryDetail {
  item: MemoryItem;
  provenance: Provenance[];
  history: MemoryEvent[];
  versions: MemoryItem[];
  relations: Relation[];
}

export interface AuditEvent {
  id: UUID;
  actor_type: ActorType;
  actor_id: UUID | null;
  actor_label: string;
  action: string;
  target_type: string;
  target_id: UUID | null;
  summary: string;
  details: JsonObject;
  created_at: ISODateString;
}

/* -------------------------------------------------------------------------- */
/* Auth & users                                                               */
/* -------------------------------------------------------------------------- */

export interface LoginIn {
  email: string;
  password: string;
}

export interface UserListParams {
  q?: string;
}

export interface UserCreateIn {
  email: string;
  full_name: string;
  password: string;
  clearance: Classification;
  is_admin: boolean;
}

export interface UserUpdateIn {
  full_name?: string;
  clearance?: Classification;
  is_admin?: boolean;
  password?: string;
}

/* -------------------------------------------------------------------------- */
/* Projects, members, agents                                                  */
/* -------------------------------------------------------------------------- */

export interface ProjectCreateIn {
  name: string;
  slug?: string;
  description?: string;
}

export interface ProjectUpdateIn {
  name?: string;
  description?: string;
  /** Partial merge of settings. */
  settings?: Partial<Omit<ProjectSettings, "freshness_days">> & {
    freshness_days?: Partial<Record<SourceKind, number>>;
  };
}

export interface OverviewStats {
  sources: number;
  documents: number;
  documents_indexed: number;
  chunks: number;
  memory_items: number;
  validated_decisions: number;
  context_requests_7d: number;
  snapshots: number;
  pii_documents: number;
  /** Documents classified C2+. */
  restricted_documents: number;
}

export interface OverviewIngestion {
  queued: number;
  running: number;
  failed: number;
  succeeded_24h: number;
}

export interface OverviewContext {
  requests_7d: number;
  p95_latency_ms: number | null;
  avg_tokens: number | null;
  avg_included: number | null;
  exclusion_rate: number | null;
}

export interface OverviewAlert {
  level: AlertLevel;
  message: string;
}

export interface Overview {
  project: Project;
  stats: OverviewStats;
  ingestion: OverviewIngestion;
  memory_by_status: Record<MemoryStatus, number>;
  memory_by_scope: Record<MemoryScope, number>;
  context: OverviewContext;
  sources_by_kind: Record<SourceKind, number>;
  /** 5 latest validated decisions. */
  latest_decisions: MemoryItem[];
  /** 15 latest audit events. */
  recent_activity: AuditEvent[];
  alerts: OverviewAlert[];
}

export interface MemberCreateIn {
  email: string;
  role: Role;
}

export interface MemberUpdateIn {
  role: Role;
}

export interface AgentCreateIn {
  name: string;
  kind: AgentKind;
  description?: string;
  clearance: Classification;
}

/* -------------------------------------------------------------------------- */
/* Sources & documents                                                        */
/* -------------------------------------------------------------------------- */

export interface SourceCreateIn {
  name: string;
  kind: SourceKind;
  description?: string;
  default_classification?: Classification;
  default_acl?: string[];
  config?: JsonObject;
  /** Owners only (AI security §A3). */
  trust?: SourceTrust;
}

export type SourceUpdateIn = Partial<SourceCreateIn>;

export interface DocumentListParams extends PageParams {
  source_id?: UUID;
  status?: DocumentStatus;
  source_kind?: SourceKind;
  classification?: Classification;
  q?: string;
}

/** Multipart fields of `POST /documents/upload`. */
export interface DocumentUploadIn {
  files: File[];
  source_id?: UUID;
  classification?: Classification;
  /** Sent as CSV. */
  acl_principals?: string[];
  /** Sent as CSV. */
  tags?: string[];
}

export interface TextDocumentIn {
  source_id?: UUID;
  /** Without `source_id`: default source of that kind, created on the fly. */
  source_kind?: SourceKind;
  title: string;
  content: string;
  external_id?: string;
  uri?: string;
  author?: string;
  classification?: Classification;
  acl_principals?: string[];
  tags?: string[];
  source_updated_at?: ISODateString;
  metadata?: JsonObject;
}

/** Multipart fields of `POST /documents/import`. */
export interface DocumentImportIn {
  /** JSON array or CSV file. */
  file: File;
  source_kind: SourceKind;
  source_id?: UUID;
}

export interface DocumentImportResult {
  created: number;
  updated: number;
  documents: DocumentSummary[];
}

export interface DocumentUpdateIn {
  title?: string;
  classification?: Classification;
  acl_principals?: string[];
  tags?: string[];
}

export interface ForgetIn {
  reason: string;
}

export interface JobListParams {
  status?: JobStatus;
  page?: number;
}

export interface SearchParams {
  q: string;
  /** Default 20. */
  limit?: number;
}

export interface SearchHit {
  chunk_id: UUID;
  document_id: UUID;
  document_title: string;
  source_kind: SourceKind;
  text: string;
  score: number;
  bm25: number | null;
  dense: number | null;
  section: string | null;
  source_updated_at: ISODateString | null;
}

/* -------------------------------------------------------------------------- */
/* Memory                                                                     */
/* -------------------------------------------------------------------------- */

export interface MemoryListParams extends PageParams {
  scope?: MemoryScope;
  kind?: MemoryKind;
  status?: MemoryStatus;
  q?: string;
  /** Default false. */
  include_history?: boolean;
}

export interface MemoryProvenanceIn {
  document_id?: UUID;
  chunk_id?: UUID;
  excerpt?: string;
  source_label?: string;
}

export interface MemoryIn {
  scope: MemoryScope;
  kind: MemoryKind;
  title: string;
  content: string;
  classification?: Classification;
  acl_principals?: string[];
  tags?: string[];
  subject_user_id?: UUID;
  session_id?: string;
  valid_from?: ISODateString;
  valid_to?: ISODateString;
  confidence?: number;
  supersedes_id?: UUID;
  status?: "proposed" | "validated";
  provenance?: MemoryProvenanceIn[];
}

export interface MemoryUpdateIn {
  title?: string;
  content?: string;
  tags?: string[];
  valid_to?: ISODateString | null;
  classification?: Classification;
  kind?: MemoryKind;
}

export interface ReasonIn {
  reason?: string;
}

export interface RequiredReasonIn {
  reason: string;
}

export interface SupersedeIn {
  by_id: UUID;
  reason?: string;
}

export interface MemoryGraphNode {
  id: UUID;
  type: RelationNodeType;
  label: string;
  kind: MemoryKind | SourceKind | null;
  status: MemoryStatus | DocumentStatus | ChunkStatus | null;
}

export interface MemoryGraphEdge {
  source: UUID;
  target: UUID;
  rel_type: RelationType;
}

export interface MemoryGraph {
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
}

/* -------------------------------------------------------------------------- */
/* Sessions (short-term memory)                                               */
/* -------------------------------------------------------------------------- */

export interface SessionTurnIn {
  role: SessionTurnRole;
  content: string;
  agent_id?: UUID;
}

export interface SessionTurnResult {
  session_id: string;
  turns: number;
  expires_at: ISODateString;
}

export interface SessionTurn {
  role: SessionTurnRole;
  content: string;
  at: ISODateString;
}

export interface SessionDetail {
  session_id: string;
  turns: SessionTurn[];
  expires_at: ISODateString | null;
  memory_items: MemoryItem[];
}

export interface SessionCloseResult {
  summary: MemoryItem | null;
}

export interface SessionSummary {
  session_id: string;
  turns: number;
  updated_at: ISODateString;
  expires_at: ISODateString | null;
}

/* -------------------------------------------------------------------------- */
/* Context                                                                    */
/* -------------------------------------------------------------------------- */

export interface SnapshotRef {
  name: string;
  version?: number;
}

export interface ContextRequestIn {
  task: string;
  intent?: Intent;
  agent_id?: UUID;
  on_behalf_of?: UUID;
  /** Min 500, max 32000. */
  token_budget?: number;
  scopes?: MemoryScope[];
  source_kinds?: SourceKind[];
  include_sources?: boolean;
  freshness_days?: number;
  max_classification?: Classification;
  min_relevance?: number;
  session_id?: string;
  base_snapshot?: SnapshotRef;
  save_snapshot?: { name: string };
  explain?: boolean;
}

export interface Scores {
  bm25?: number;
  dense?: number;
  rrf?: number;
  rerank?: number;
  freshness?: number;
  final: number;
}

export interface ContextItem {
  /** "S1", "S2", … */
  citation: string;
  candidate_type: CandidateType;
  id: UUID | string;
  document_id?: UUID | null;
  memory_item_id?: UUID | null;
  title: string;
  source_kind?: SourceKind | null;
  memory_kind?: MemoryKind | null;
  memory_scope?: MemoryScope | null;
  uri?: string | null;
  version?: number | null;
  /** Compressed text actually served. */
  excerpt: string;
  tokens: number;
  scores: Scores;
  classification: Classification;
  /** source_updated_at or valid_from. */
  date: ISODateString | null;
  pii_redacted: boolean;
  reason_code: "INCLUDED_RELEVANT" | "INCLUDED_PINNED";
  reason_detail: string;
}

export interface ExcludedItem {
  candidate_type: CandidateType;
  id?: UUID | string;
  title?: string;
  excerpt?: string;
  source_kind?: SourceKind | null;
  memory_kind?: MemoryKind | null;
  classification?: Classification;
  scores: Scores;
  reason_code: ReasonCode;
  reason_detail: string;
  redacted: boolean;
  /** e.g. duplicate of S3. */
  related_citation?: string | null;
}

export type RetrievalQueryKind = "task" | "multi" | "hyde" | "expansion" | "subtopic" | (string & {});

export interface RetrievalQuery {
  text: string;
  kind: RetrievalQueryKind;
}

/** One round of iterative retrieval (AI_CONTEXT_ENGINEERING §B4). */
export interface RetrievalRound {
  round: number;
  queries: RetrievalQuery[];
  new_items: number;
  uncovered: string[];
  ms: number;
}

export interface ContextTimings {
  understand: number;
  rewrite?: number;
  retrieve: number;
  fuse: number;
  rerank: number;
  govern: number;
  select: number;
  compress: number;
  package: number;
  total: number;
  rounds?: RetrievalRound[];
}

export interface ContextConfig {
  retrieval: "hybrid-bm25-knn-rrf-v1" | (string & {});
  reranker: string;
  embedding_model: string;
  llm: string | null;
}

export interface ContextPackage {
  request_id: UUID;
  trace_id: string;
  task: string;
  intent: Intent;
  created_at: ISODateString;
  /** Assembled Markdown with [S1]… citations. */
  context: string;
  /** Included items, in presentation order. */
  items: ContextItem[];
  /** Empty when explain=false. */
  excluded: ExcludedItem[];
  exclusion_summary: Partial<Record<ReasonCode, number>>;
  tokens_used: number;
  token_budget: number;
  candidates_count: number;
  timings: ContextTimings;
  snapshot: { id: UUID; name: string; version: number } | null;
  config: ContextConfig;
  warnings: string[];
  /** §C1 prompt cache: SHA-256 of the stable prefix of `context` (null when the layout is disabled). */
  cache_prefix_hash?: string | null;
  cache_prefix_tokens?: number;
  /** A request of this project served the same prefix within the cache window. */
  cache_prefix_reused?: boolean;
  /** Anthropic text blocks (requested with `cache_hints: true`); `cache_control` closes the prefix. */
  cache_hints?: { type: "text"; text: string; cache_control: { type: "ephemeral" } | null }[] | null;
}

export interface FeedbackItemFlag {
  citation: string;
  flag: FeedbackFlag;
}

export interface ContextFeedbackIn {
  /** 1..5 */
  rating: number;
  comment?: string;
  item_flags?: FeedbackItemFlag[];
}

/**
 * Feedback entry attached to a reconstituted context request.
 * Shape not detailed in API.md: derived from the `context_feedback` table (ARCHITECTURE §5).
 */
export interface ContextFeedback {
  id: UUID;
  actor_type: ActorType;
  actor_id: UUID | null;
  actor_label?: string | null;
  rating: number;
  comment: string | null;
  item_flags: FeedbackItemFlag[];
  created_at: ISODateString;
}

/** `GET /context/requests/{id}` — reconstituted package with its feedback. */
export type ContextRequestDetail = ContextPackage & { feedback: ContextFeedback[] };

export interface ContextRequestListParams {
  agent_id?: UUID;
  page?: number;
}

export interface ContextRequestSummary {
  id: UUID;
  trace_id: string;
  task: string;
  intent: Intent;
  agent: { id: UUID; name: string; kind: AgentKind } | null;
  user: { id: UUID; full_name: string } | null;
  latency_ms: number;
  tokens_used: number;
  token_budget: number;
  included_count: number;
  excluded_count: number;
  candidates_count: number;
  snapshot: { name: string; version: number } | null;
  rating: number | null;
  created_at: ISODateString;
}

/* -------------------------------------------------------------------------- */
/* Snapshots                                                                  */
/* -------------------------------------------------------------------------- */

export interface SnapshotListItem {
  name: string;
  latest_version: number;
  versions: number;
  updated_at: ISODateString;
  last_task: string;
}

export interface SnapshotSummary {
  id: UUID;
  name: string;
  version: number;
  parent_version: number | null;
  task: string;
  intent: Intent;
  token_count: number;
  items_count: number;
  content_hash: string;
  created_by_label: string | null;
  created_at: ISODateString;
}

export interface SnapshotItem {
  /** "chunk:<id>" | "memory:<lineage_id>" */
  key: string;
  citation: string;
  candidate_type: CandidateType;
  id: UUID | string;
  title: string;
  excerpt: string;
  source_kind?: SourceKind | null;
  memory_kind?: MemoryKind | null;
  version?: number | null;
  forgotten: boolean;
}

export type Snapshot = SnapshotSummary & {
  content: string;
  items: SnapshotItem[];
  request_id: UUID | null;
};

/** `latest` is accepted as a version. */
export type SnapshotVersionRef = number | "latest";

export interface SnapshotDiffParams {
  from: number;
  to: number;
}

export interface SnapshotDiff {
  from: number;
  to: number;
  added: SnapshotItem[];
  removed: SnapshotItem[];
  unchanged: SnapshotItem[];
}

/* -------------------------------------------------------------------------- */
/* Observability & audit                                                      */
/* -------------------------------------------------------------------------- */

export interface MetricsParams {
  /** Default 14. */
  days?: number;
}

export interface MetricsTotals {
  requests: number;
  avg_latency_ms: number | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  tokens: number;
  cost_estimate: number;
  avg_rating: number | null;
  feedback_count: number;
}

export interface MetricsSeriesPoint {
  /** YYYY-MM-DD */
  date: string;
  requests: number;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  tokens: number;
  cost_estimate: number;
}

export interface MetricsTopSource {
  document_id: UUID;
  title: string;
  source_kind: SourceKind;
  count: number;
}

export interface MetricsByAgent {
  agent_id: UUID;
  name: string;
  kind: AgentKind;
  requests: number;
  avg_latency_ms: number | null;
  avg_tokens: number | null;
}

export interface MetricsIngestion {
  documents_by_status: Record<DocumentStatus, number>;
  jobs_by_status: Record<JobStatus, number>;
  avg_ingest_ms: number | null;
}

export interface Metrics {
  totals: MetricsTotals;
  /** One point per day. */
  series: MetricsSeriesPoint[];
  exclusions_by_reason: Partial<Record<ReasonCode, number>>;
  /** chunk / memory:decision / … */
  inclusions_by_type: Record<string, number>;
  top_sources: MetricsTopSource[];
  by_agent: MetricsByAgent[];
  /** understand/retrieve/… */
  stage_latency_avg: Record<string, number>;
  ingestion: MetricsIngestion;
  /** §C1 prompt-cache reuse of stable prefixes. */
  cache?: MetricsCache;
}

export interface MetricsCache {
  packages: number;
  reused: number;
  reuse_rate: number;
  avg_prefix_tokens: number;
  reused_prefix_tokens: number;
}

export interface AuditListParams {
  action?: string;
  page?: number;
}

export interface TraceExportParams {
  /** Default 30. */
  days?: number;
}

/* -------------------------------------------------------------------------- */
/* System                                                                     */
/* -------------------------------------------------------------------------- */

export interface Meta {
  version: string;
  embedding_model: string;
  reranker: string;
  llm: string | null;
  reason_codes: Record<ReasonCode, string>;
}

export interface CreatedId {
  id: UUID;
}
