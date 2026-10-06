/**
 * One typed function per endpoint of docs/API.md (base `/api/v1`).
 * Path segments are always URI-encoded. `signal` is forwarded for query cancellation.
 */
import { apiUrl, http, request } from "./client";
import type {
  Agent,
  AgentCreateIn,
  AgentCreated,
  AuditEvent,
  AuditListParams,
  ChunkView,
  ContextFeedbackIn,
  ContextPackage,
  ContextRequestDetail,
  ContextRequestIn,
  ContextRequestListParams,
  ContextRequestSummary,
  CreatedId,
  DocumentDetail,
  DocumentImportIn,
  DocumentImportResult,
  DocumentListParams,
  DocumentSummary,
  DocumentUpdateIn,
  DocumentUploadIn,
  ForgetIn,
  Job,
  JobListParams,
  JobWithDocument,
  LoginIn,
  Member,
  MemberCreateIn,
  MemberUpdateIn,
  MemoryDetail,
  MemoryGraph,
  MemoryIn,
  MemoryItem,
  MemoryListParams,
  MemoryUpdateIn,
  Meta,
  Metrics,
  MetricsParams,
  Overview,
  Page,
  Project,
  ProjectCreateIn,
  ProjectSummary,
  ProjectUpdateIn,
  ReasonIn,
  RequiredReasonIn,
  SearchHit,
  SearchParams,
  SessionCloseResult,
  SessionDetail,
  SessionSummary,
  SessionTurnIn,
  SessionTurnResult,
  Snapshot,
  SnapshotDiff,
  SnapshotDiffParams,
  SnapshotListItem,
  SnapshotSummary,
  SnapshotVersionRef,
  SupersedeIn,
  QuarantinedChunk,
  Source,
  SourceCreateIn,
  SourceUpdateIn,
  TextDocumentIn,
  TraceExportParams,
  User,
  UserCreateIn,
  UserListParams,
  UserUpdateIn,
  UUID,
} from "./types";

type Opts = { signal?: AbortSignal };

const e = encodeURIComponent;
const p = (slug: string) => `/projects/${e(slug)}`;

/* -------------------------------------------------------------------------- */
/* Auth & users                                                               */
/* -------------------------------------------------------------------------- */

/** POST /auth/login → User (+ `orbit_session` cookie). Never redirects on 401. */
export function login(body: LoginIn): Promise<User> {
  return http.post<User>("/auth/login", body, { redirectOnUnauthorized: false });
}

/** POST /auth/logout → 204 */
export function logout(): Promise<void> {
  return http.post<void>("/auth/logout", undefined, { redirectOnUnauthorized: false });
}

/**
 * GET /auth/me → User.
 * `redirectOnUnauthorized` defaults to true (auth guard); the login page passes false.
 */
export function getMe(opts: Opts & { redirectOnUnauthorized?: boolean } = {}): Promise<User> {
  return http.get<User>("/auth/me", opts);
}

/** GET /users (admin) → User[] */
export function listUsers(params: UserListParams = {}, opts: Opts = {}): Promise<User[]> {
  return http.get<User[]>("/users", { query: { q: params.q }, ...opts });
}

/** POST /users (admin) → User */
export function createUser(body: UserCreateIn): Promise<User> {
  return http.post<User>("/users", body);
}

/** PATCH /users/{id} (admin) → User */
export function updateUser(id: UUID, body: UserUpdateIn): Promise<User> {
  return http.patch<User>(`/users/${e(id)}`, body);
}

/* -------------------------------------------------------------------------- */
/* Projects                                                                   */
/* -------------------------------------------------------------------------- */

/** GET /projects → ProjectSummary[] */
export function listProjects(opts: Opts = {}): Promise<ProjectSummary[]> {
  return http.get<ProjectSummary[]>("/projects", opts);
}

/** POST /projects → Project (caller becomes owner) */
export function createProject(body: ProjectCreateIn): Promise<Project> {
  return http.post<Project>("/projects", body);
}

/** GET /projects/{slug} → Project */
export function getProject(slug: string, opts: Opts = {}): Promise<Project> {
  return http.get<Project>(p(slug), opts);
}

/** PATCH /projects/{slug} (owner) → Project */
export function updateProject(slug: string, body: ProjectUpdateIn): Promise<Project> {
  return http.patch<Project>(p(slug), body);
}

/** GET /projects/{slug}/overview → Overview */
export function getProjectOverview(slug: string, opts: Opts = {}): Promise<Overview> {
  return http.get<Overview>(`${p(slug)}/overview`, opts);
}

/* -------------------------------------------------------------------------- */
/* Members                                                                    */
/* -------------------------------------------------------------------------- */

/** GET /projects/{slug}/members → Member[] */
export function listMembers(slug: string, opts: Opts = {}): Promise<Member[]> {
  return http.get<Member[]>(`${p(slug)}/members`, opts);
}

/** POST /projects/{slug}/members (owner) → Member */
export function addMember(slug: string, body: MemberCreateIn): Promise<Member> {
  return http.post<Member>(`${p(slug)}/members`, body);
}

/** PATCH /projects/{slug}/members/{user_id} (owner) → Member */
export function updateMember(slug: string, userId: UUID, body: MemberUpdateIn): Promise<Member> {
  return http.patch<Member>(`${p(slug)}/members/${e(userId)}`, body);
}

/** DELETE /projects/{slug}/members/{user_id} (owner) → 204 (409 if last owner) */
export function removeMember(slug: string, userId: UUID): Promise<void> {
  return http.delete<void>(`${p(slug)}/members/${e(userId)}`);
}

/* -------------------------------------------------------------------------- */
/* Agents                                                                     */
/* -------------------------------------------------------------------------- */

/** GET /projects/{slug}/agents → Agent[] */
export function listAgents(slug: string, opts: Opts = {}): Promise<Agent[]> {
  return http.get<Agent[]>(`${p(slug)}/agents`, opts);
}

/** POST /projects/{slug}/agents (owner) → AgentCreated (key shown once) */
export function createAgent(slug: string, body: AgentCreateIn): Promise<AgentCreated> {
  return http.post<AgentCreated>(`${p(slug)}/agents`, body);
}

/** POST /projects/{slug}/agents/{id}/rotate (owner) → AgentCreated */
export function rotateAgentKey(slug: string, agentId: UUID): Promise<AgentCreated> {
  return http.post<AgentCreated>(`${p(slug)}/agents/${e(agentId)}/rotate`);
}

/** DELETE /projects/{slug}/agents/{id} (owner) → 204 (revocation: active=false) */
export function revokeAgent(slug: string, agentId: UUID): Promise<void> {
  return http.delete<void>(`${p(slug)}/agents/${e(agentId)}`);
}

/* -------------------------------------------------------------------------- */
/* Sources                                                                    */
/* -------------------------------------------------------------------------- */

/** GET /projects/{slug}/sources → Source[] */
export function listSources(slug: string, opts: Opts = {}): Promise<Source[]> {
  return http.get<Source[]>(`${p(slug)}/sources`, opts);
}

/** POST /projects/{slug}/sources (editor) → Source */
export function createSource(slug: string, body: SourceCreateIn): Promise<Source> {
  return http.post<Source>(`${p(slug)}/sources`, body);
}

/** PATCH /projects/{slug}/sources/{id} (editor) → Source */
export function updateSource(slug: string, sourceId: UUID, body: SourceUpdateIn): Promise<Source> {
  return http.patch<Source>(`${p(slug)}/sources/${e(sourceId)}`, body);
}

/* -------------------------------------------------------------------------- */
/* Documents                                                                  */
/* -------------------------------------------------------------------------- */

/** GET /projects/{slug}/documents → Page<DocumentSummary> */
export function listDocuments(
  slug: string,
  params: DocumentListParams = {},
  opts: Opts = {},
): Promise<Page<DocumentSummary>> {
  return http.get<Page<DocumentSummary>>(`${p(slug)}/documents`, {
    query: {
      source_id: params.source_id,
      status: params.status,
      source_kind: params.source_kind,
      classification: params.classification,
      q: params.q,
      page: params.page,
      page_size: params.page_size,
    },
    ...opts,
  });
}

/** POST /projects/{slug}/documents/upload (editor, multipart) → DocumentSummary[] (status `pending`) */
export function uploadDocuments(slug: string, input: DocumentUploadIn): Promise<DocumentSummary[]> {
  const form = new FormData();
  for (const file of input.files) form.append("files", file, file.name);
  if (input.source_id) form.append("source_id", input.source_id);
  if (input.classification !== undefined) form.append("classification", String(input.classification));
  if (input.acl_principals?.length) form.append("acl_principals", input.acl_principals.join(","));
  if (input.tags?.length) form.append("tags", input.tags.join(","));
  return http.upload<DocumentSummary[]>(`${p(slug)}/documents/upload`, form);
}

/** POST /projects/{slug}/documents/text (editor) → DocumentSummary */
export function createTextDocument(slug: string, body: TextDocumentIn): Promise<DocumentSummary> {
  return http.post<DocumentSummary>(`${p(slug)}/documents/text`, body);
}

/** POST /projects/{slug}/documents/import (editor, multipart JSON/CSV) → {created, updated, documents} */
export function importDocuments(slug: string, input: DocumentImportIn): Promise<DocumentImportResult> {
  const form = new FormData();
  form.append("file", input.file, input.file.name);
  form.append("source_kind", input.source_kind);
  if (input.source_id) form.append("source_id", input.source_id);
  return http.upload<DocumentImportResult>(`${p(slug)}/documents/import`, form);
}

/** GET /projects/{slug}/documents/{id} → DocumentDetail (404 if not accessible) */
export function getDocument(slug: string, documentId: UUID, opts: Opts = {}): Promise<DocumentDetail> {
  return http.get<DocumentDetail>(`${p(slug)}/documents/${e(documentId)}`, opts);
}

/** PATCH /projects/{slug}/documents/{id} (editor) → DocumentSummary */
export function updateDocument(slug: string, documentId: UUID, body: DocumentUpdateIn): Promise<DocumentSummary> {
  return http.patch<DocumentSummary>(`${p(slug)}/documents/${e(documentId)}`, body);
}

/** POST /projects/{slug}/documents/{id}/reprocess (editor) → Job */
export function reprocessDocument(slug: string, documentId: UUID): Promise<Job> {
  return http.post<Job>(`${p(slug)}/documents/${e(documentId)}/reprocess`);
}

/** POST /projects/{slug}/documents/{id}/forget (owner) → DocumentSummary (status `forgotten`) */
export function forgetDocument(slug: string, documentId: UUID, body: ForgetIn): Promise<DocumentSummary> {
  return http.post<DocumentSummary>(`${p(slug)}/documents/${e(documentId)}/forget`, body);
}

/** URL of GET /projects/{slug}/documents/{id}/raw (editor) — usable as <a href download>. */
export function documentRawUrl(slug: string, documentId: UUID): string {
  return apiUrl(`${p(slug)}/documents/${e(documentId)}/raw`);
}

/** GET /projects/{slug}/documents/{id}/raw (editor) → original file as Blob. */
export function downloadDocumentRaw(slug: string, documentId: UUID, opts: Opts = {}): Promise<Blob> {
  return request<Blob>(`${p(slug)}/documents/${e(documentId)}/raw`, { responseType: "blob", ...opts });
}

/* -------------------------------------------------------------------------- */
/* Jobs & search                                                              */
/* -------------------------------------------------------------------------- */

/** GET /projects/{slug}/jobs → Page<Job & {document_title}> */
export function listJobs(slug: string, params: JobListParams = {}, opts: Opts = {}): Promise<Page<JobWithDocument>> {
  return http.get<Page<JobWithDocument>>(`${p(slug)}/jobs`, {
    query: { status: params.status, page: params.page },
    ...opts,
  });
}

/** GET /projects/{slug}/search → SearchHit[] (hybrid, filtered by caller rights) */
export function searchProject(slug: string, params: SearchParams, opts: Opts = {}): Promise<SearchHit[]> {
  return http.get<SearchHit[]>(`${p(slug)}/search`, { query: { q: params.q, limit: params.limit }, ...opts });
}

/* -------------------------------------------------------------------------- */
/* Memory                                                                     */
/* -------------------------------------------------------------------------- */

/** GET /projects/{slug}/memory → Page<MemoryItem> */
export function listMemory(slug: string, params: MemoryListParams = {}, opts: Opts = {}): Promise<Page<MemoryItem>> {
  return http.get<Page<MemoryItem>>(`${p(slug)}/memory`, {
    query: {
      scope: params.scope,
      kind: params.kind,
      status: params.status,
      q: params.q,
      include_history: params.include_history,
      page: params.page,
      page_size: params.page_size,
    },
    ...opts,
  });
}

/** POST /projects/{slug}/memory (editor) → MemoryItem */
export function createMemory(slug: string, body: MemoryIn): Promise<MemoryItem> {
  return http.post<MemoryItem>(`${p(slug)}/memory`, body);
}

/** GET /projects/{slug}/memory/{id} → MemoryDetail */
export function getMemory(slug: string, memoryId: UUID, opts: Opts = {}): Promise<MemoryDetail> {
  return http.get<MemoryDetail>(`${p(slug)}/memory/${e(memoryId)}`, opts);
}

/** PATCH /projects/{slug}/memory/{id} (editor) → MemoryItem (new version) */
export function updateMemory(slug: string, memoryId: UUID, body: MemoryUpdateIn): Promise<MemoryItem> {
  return http.patch<MemoryItem>(`${p(slug)}/memory/${e(memoryId)}`, body);
}

/** POST /projects/{slug}/memory/{id}/validate (editor) → MemoryItem */
export function validateMemory(slug: string, memoryId: UUID, body: ReasonIn = {}): Promise<MemoryItem> {
  return http.post<MemoryItem>(`${p(slug)}/memory/${e(memoryId)}/validate`, body);
}

/** POST /projects/{slug}/memory/{id}/obsolete (editor) → MemoryItem */
export function obsoleteMemory(slug: string, memoryId: UUID, body: RequiredReasonIn): Promise<MemoryItem> {
  return http.post<MemoryItem>(`${p(slug)}/memory/${e(memoryId)}/obsolete`, body);
}

/** POST /projects/{slug}/memory/{id}/supersede (editor) → MemoryItem (the old one) */
export function supersedeMemory(
  slug: string,
  memoryId: UUID,
  body: SupersedeIn,
): Promise<MemoryItem> {
  return http.post<MemoryItem>(`${p(slug)}/memory/${e(memoryId)}/supersede`, body);
}

/** POST /projects/{slug}/memory/{id}/restore (editor) → MemoryItem */
export function restoreMemory(slug: string, memoryId: UUID, body: ReasonIn = {}): Promise<MemoryItem> {
  return http.post<MemoryItem>(`${p(slug)}/memory/${e(memoryId)}/restore`, body);
}

/** POST /projects/{slug}/memory/{id}/forget (owner, or subject for scope `user`) → MemoryItem */
export function forgetMemory(slug: string, memoryId: UUID, body: RequiredReasonIn): Promise<MemoryItem> {
  return http.post<MemoryItem>(`${p(slug)}/memory/${e(memoryId)}/forget`, body);
}

/** POST /projects/{slug}/memory/consolidate (editor) → Job */
export function consolidateMemory(slug: string): Promise<Job> {
  return http.post<Job>(`${p(slug)}/memory/consolidate`);
}

/** GET /projects/{slug}/memory/graph → {nodes, edges} */
export function getMemoryGraph(slug: string, params: { limit?: number } = {}, opts: Opts = {}): Promise<MemoryGraph> {
  return http.get<MemoryGraph>(`${p(slug)}/memory/graph`, { query: { limit: params.limit }, ...opts });
}

/* -------------------------------------------------------------------------- */
/* Sessions (short-term memory)                                               */
/* -------------------------------------------------------------------------- */

/** POST /projects/{slug}/sessions/{session_id}/turns (editor) → {session_id, turns, expires_at} */
export function addSessionTurn(slug: string, sessionId: string, body: SessionTurnIn): Promise<SessionTurnResult> {
  return http.post<SessionTurnResult>(`${p(slug)}/sessions/${e(sessionId)}/turns`, body);
}

/** GET /projects/{slug}/sessions/{session_id} → SessionDetail */
export function getSession(slug: string, sessionId: string, opts: Opts = {}): Promise<SessionDetail> {
  return http.get<SessionDetail>(`${p(slug)}/sessions/${e(sessionId)}`, opts);
}

/** POST /projects/{slug}/sessions/{session_id}/close (editor) → {summary} */
export function closeSession(slug: string, sessionId: string): Promise<SessionCloseResult> {
  return http.post<SessionCloseResult>(`${p(slug)}/sessions/${e(sessionId)}/close`);
}

/** GET /projects/{slug}/sessions → SessionSummary[] */
export function listSessions(slug: string, opts: Opts = {}): Promise<SessionSummary[]> {
  return http.get<SessionSummary[]>(`${p(slug)}/sessions`, opts);
}

/* -------------------------------------------------------------------------- */
/* Context                                                                    */
/* -------------------------------------------------------------------------- */

/** POST /projects/{slug}/context → ContextPackage */
export function assembleContext(slug: string, body: ContextRequestIn): Promise<ContextPackage> {
  return http.post<ContextPackage>(`${p(slug)}/context`, body);
}

/** GET /projects/{slug}/context/requests → Page<ContextRequestSummary> */
export function listContextRequests(
  slug: string,
  params: ContextRequestListParams = {},
  opts: Opts = {},
): Promise<Page<ContextRequestSummary>> {
  return http.get<Page<ContextRequestSummary>>(`${p(slug)}/context/requests`, {
    query: { agent_id: params.agent_id, page: params.page },
    ...opts,
  });
}

/** GET /projects/{slug}/context/requests/{id} → ContextPackage (+ feedback[]) */
export function getContextRequest(slug: string, requestId: UUID, opts: Opts = {}): Promise<ContextRequestDetail> {
  return http.get<ContextRequestDetail>(`${p(slug)}/context/requests/${e(requestId)}`, opts);
}

/** POST /projects/{slug}/context/requests/{id}/feedback → {id} */
export function sendContextFeedback(slug: string, requestId: UUID, body: ContextFeedbackIn): Promise<CreatedId> {
  return http.post<CreatedId>(`${p(slug)}/context/requests/${e(requestId)}/feedback`, body);
}

/* -------------------------------------------------------------------------- */
/* Snapshots                                                                  */
/* -------------------------------------------------------------------------- */

/** GET /projects/{slug}/snapshots → {name, latest_version, versions, updated_at, last_task}[] */
export function listSnapshots(slug: string, opts: Opts = {}): Promise<SnapshotListItem[]> {
  return http.get<SnapshotListItem[]>(`${p(slug)}/snapshots`, opts);
}

/** GET /projects/{slug}/snapshots/{name} → SnapshotSummary[] (versions, desc) */
export function listSnapshotVersions(slug: string, name: string, opts: Opts = {}): Promise<SnapshotSummary[]> {
  return http.get<SnapshotSummary[]>(`${p(slug)}/snapshots/${e(name)}`, opts);
}

/** GET /projects/{slug}/snapshots/{name}/{version} → Snapshot (`latest` accepted) */
export function getSnapshot(
  slug: string,
  name: string,
  version: SnapshotVersionRef = "latest",
  opts: Opts = {},
): Promise<Snapshot> {
  return http.get<Snapshot>(`${p(slug)}/snapshots/${e(name)}/${e(String(version))}`, opts);
}

/** GET /projects/{slug}/snapshots/{name}/diff?from=&to= → SnapshotDiff */
export function diffSnapshot(
  slug: string,
  name: string,
  params: SnapshotDiffParams,
  opts: Opts = {},
): Promise<SnapshotDiff> {
  return http.get<SnapshotDiff>(`${p(slug)}/snapshots/${e(name)}/diff`, {
    query: { from: params.from, to: params.to },
    ...opts,
  });
}

/* -------------------------------------------------------------------------- */
/* Observability & audit                                                      */
/* -------------------------------------------------------------------------- */

/** GET /projects/{slug}/metrics?days= → Metrics */
export function getMetrics(slug: string, params: MetricsParams = {}, opts: Opts = {}): Promise<Metrics> {
  return http.get<Metrics>(`${p(slug)}/metrics`, { query: { days: params.days }, ...opts });
}

/** GET /projects/{slug}/audit → Page<AuditEvent> */
export function listAudit(slug: string, params: AuditListParams = {}, opts: Opts = {}): Promise<Page<AuditEvent>> {
  return http.get<Page<AuditEvent>>(`${p(slug)}/audit`, {
    query: { action: params.action, page: params.page },
    ...opts,
  });
}

/** URL of GET /projects/{slug}/traces/export (owner, NDJSON) — usable as <a href download>. */
export function traceExportUrl(slug: string, params: TraceExportParams = {}): string {
  return apiUrl(`${p(slug)}/traces/export`, { days: params.days });
}

/** GET /projects/{slug}/traces/export (owner) → NDJSON text (one line per context request). */
export function exportTraces(slug: string, params: TraceExportParams = {}, opts: Opts = {}): Promise<string> {
  return request<string>(`${p(slug)}/traces/export`, {
    query: { days: params.days },
    responseType: "text",
    ...opts,
  });
}

/* -------------------------------------------------------------------------- */
/* AI security (quarantine, AI Act traceability report)                       */
/* -------------------------------------------------------------------------- */

/** GET /projects/{slug}/documents/quarantine (owner) → chunks held in quarantine. */
export function listQuarantine(slug: string, opts: Opts = {}): Promise<QuarantinedChunk[]> {
  return http.get<QuarantinedChunk[]>(`${p(slug)}/documents/quarantine`, opts);
}

/** POST /projects/{slug}/documents/{id}/chunks/{chunk}/release (owner, audited) → ChunkView */
export function releaseQuarantine(slug: string, documentId: UUID, chunkId: UUID): Promise<ChunkView> {
  return http.post<ChunkView>(`${p(slug)}/documents/${e(documentId)}/chunks/${e(chunkId)}/release`);
}

export interface ComplianceReportParams {
  format?: "json" | "html";
  request_id?: string;
  memory_id?: string;
  from?: string;
  to?: string;
}

/** URL of GET /projects/{slug}/compliance/report (owner) — JSON download or printable HTML. */
export function complianceReportUrl(slug: string, params: ComplianceReportParams = {}): string {
  return apiUrl(`${p(slug)}/compliance/report`, {
    format: params.format,
    request_id: params.request_id || undefined,
    memory_id: params.memory_id || undefined,
    from: params.from || undefined,
    to: params.to || undefined,
  });
}

/* -------------------------------------------------------------------------- */
/* System                                                                     */
/* -------------------------------------------------------------------------- */

/** GET /api/v1/meta → {version, embedding_model, reranker, llm, reason_codes} */
export function getMeta(opts: Opts = {}): Promise<Meta> {
  return http.get<Meta>("/meta", { ...opts, redirectOnUnauthorized: false });
}
