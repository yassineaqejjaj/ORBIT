"use client";

/**
 * TanStack Query v5 hooks for every endpoint of docs/API.md.
 * - Queries: `use<Resource>(…)`, all keyed through `queryKeys` (see ./query-keys.ts).
 * - Mutations: `use<Action>(slug?)`, each invalidating the affected caches on success.
 * - All mutation errors are toasted globally (see Providers) unless `meta: { silentError: true }`.
 */
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type QueryKey,
  type UseMutationOptions,
  type UseMutationResult,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";

import { saveBlob, type ApiError } from "./client";
import * as api from "./endpoints";
import type { AgentKind } from "@/lib/enums";
import { queryKeys } from "./query-keys";
import type {
  Entity,
  EntitySuggestion,
  Skill,
  Agent,
  AgentCreateIn,
  ContextProfileIn,
  ContextProfileView,
  AgentCreated,
  AuditEvent,
  AuditListParams,
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
  Job,
  JobListParams,
  JobWithDocument,
  LoginIn,
  Member,
  MemberCreateIn,
  MemoryDetail,
  MemoryGraph,
  MemoryIn,
  MemoryItem,
  MemoryListParams,
  MemoryUpdateIn,
  Meta,
  Metrics,
  Overview,
  Page,
  Project,
  ProjectCreateIn,
  ProjectSummary,
  ProjectUpdateIn,
  SearchHit,
  SessionCloseResult,
  SessionDetail,
  SessionSummary,
  SessionTurnIn,
  SessionTurnResult,
  Snapshot,
  SnapshotDiff,
  SnapshotListItem,
  SnapshotSummary,
  SnapshotVersionRef,
  Source,
  SourceCreateIn,
  SourceUpdateIn,
  TextDocumentIn,
  User,
  UserCreateIn,
  UserListParams,
  UserUpdateIn,
  UUID,
} from "./types";

export { queryKeys } from "./query-keys";

/* -------------------------------------------------------------------------- */
/* Option helpers                                                             */
/* -------------------------------------------------------------------------- */

/** Extra options accepted by every query hook. */
export type QueryOpts<T> = Omit<UseQueryOptions<T, ApiError, T, QueryKey>, "queryKey" | "queryFn">;

/** Extra options accepted by every mutation hook. */
export type MutationOpts<TData, TVars> = Omit<UseMutationOptions<TData, ApiError, TVars>, "mutationFn">;

type Invalidate<TData, TVars> = (qc: QueryClient, data: TData, vars: TVars) => Promise<unknown> | unknown;

function useApiMutation<TData, TVars>(
  mutationFn: (vars: TVars) => Promise<TData>,
  invalidate: Invalidate<TData, TVars> | null,
  options?: MutationOpts<TData, TVars>,
): UseMutationResult<TData, ApiError, TVars> {
  const qc = useQueryClient();
  return useMutation<TData, ApiError, TVars>({
    ...options,
    mutationFn,
    onSuccess: async (...args) => {
      const [data, vars] = args;
      if (invalidate) await invalidate(qc, data, vars);
      return options?.onSuccess?.(...args);
    },
  });
}

const inv = (qc: QueryClient, ...keys: QueryKey[]) =>
  Promise.all(keys.map((queryKey) => qc.invalidateQueries({ queryKey })));

/** Poll while a document is still being processed. */
const ACTIVE_DOC_STATUSES = new Set(["pending", "processing"]);
const ACTIVE_JOB_STATUSES = new Set(["queued", "running"]);
const POLL_MS = 2500;

/* -------------------------------------------------------------------------- */
/* Auth & users                                                               */
/* -------------------------------------------------------------------------- */

/** Current user (`GET /auth/me`). 401 redirects to /login unless `redirectOnUnauthorized: false`. */
export function useMe(
  options?: QueryOpts<User> & { redirectOnUnauthorized?: boolean },
): UseQueryResult<User, ApiError> {
  const { redirectOnUnauthorized = true, ...rest } = options ?? {};
  return useQuery<User, ApiError>({
    queryKey: queryKeys.me(),
    queryFn: ({ signal }) => api.getMe({ signal, redirectOnUnauthorized }),
    staleTime: 5 * 60_000,
    retry: false,
    ...rest,
  });
}

export function useLogin(options?: MutationOpts<User, LoginIn>) {
  return useApiMutation<User, LoginIn>(
    api.login,
    (qc, user) => {
      qc.removeQueries({ predicate: (q) => q.queryKey[0] === "orbit" && q.queryKey[1] !== "me" });
      qc.setQueryData(queryKeys.me(), user);
    },
    { meta: { silentError: true }, ...options },
  );
}

/** Logs out and performs a full navigation to /login (drops every cached query). */
export function useLogout(options?: MutationOpts<void, void>) {
  return useMutation<void, ApiError, void>({
    ...options,
    mutationFn: () => api.logout(),
    meta: { silentError: true },
    onSettled: (...args) => {
      options?.onSettled?.(...args);
      if (typeof window !== "undefined") window.location.replace("/login");
    },
  });
}

export function useUsers(params: UserListParams = {}, options?: QueryOpts<User[]>) {
  return useQuery<User[], ApiError>({
    queryKey: queryKeys.users.list(params),
    queryFn: ({ signal }) => api.listUsers(params, { signal }),
    ...options,
  });
}

export function useCreateUser(options?: MutationOpts<User, UserCreateIn>) {
  return useApiMutation<User, UserCreateIn>(api.createUser, (qc) => inv(qc, queryKeys.users.all()), options);
}

export function useUpdateUser(options?: MutationOpts<User, { id: UUID; body: UserUpdateIn }>) {
  return useApiMutation<User, { id: UUID; body: UserUpdateIn }>(
    ({ id, body }) => api.updateUser(id, body),
    (qc, user) => {
      const me = qc.getQueryData<User>(queryKeys.me());
      if (me?.id === user.id) qc.setQueryData(queryKeys.me(), user);
      return inv(qc, queryKeys.users.all());
    },
    options,
  );
}

/* -------------------------------------------------------------------------- */
/* Projects                                                                   */
/* -------------------------------------------------------------------------- */

export function useProjects(options?: QueryOpts<ProjectSummary[]>) {
  return useQuery<ProjectSummary[], ApiError>({
    queryKey: queryKeys.projects.list(),
    queryFn: ({ signal }) => api.listProjects({ signal }),
    ...options,
  });
}

/** Project by slug (`GET /projects/{slug}`) — includes the caller's `role`. */
export function useProject(slug: string | undefined, options?: QueryOpts<Project>) {
  return useQuery<Project, ApiError>({
    queryKey: queryKeys.project.detail(slug ?? ""),
    queryFn: ({ signal }) => api.getProject(slug as string, { signal }),
    enabled: Boolean(slug),
    staleTime: 60_000,
    ...options,
  });
}

export function useProjectOverview(slug: string, options?: QueryOpts<Overview>) {
  return useQuery<Overview, ApiError>({
    queryKey: queryKeys.project.overview(slug),
    queryFn: ({ signal }) => api.getProjectOverview(slug, { signal }),
    enabled: Boolean(slug),
    ...options,
  });
}

export function useCreateProject(options?: MutationOpts<Project, ProjectCreateIn>) {
  return useApiMutation<Project, ProjectCreateIn>(
    api.createProject,
    (qc, project) => {
      qc.setQueryData(queryKeys.project.detail(project.slug), project);
      return inv(qc, queryKeys.projects.all());
    },
    options,
  );
}

export function useUpdateProject(slug: string, options?: MutationOpts<Project, ProjectUpdateIn>) {
  return useApiMutation<Project, ProjectUpdateIn>(
    (body) => api.updateProject(slug, body),
    (qc, project) => {
      qc.setQueryData(queryKeys.project.detail(slug), project);
      return inv(qc, queryKeys.projects.all(), queryKeys.project.overview(slug));
    },
    options,
  );
}

export function useContextProfiles(slug: string, options?: QueryOpts<ContextProfileView[]>) {
  return useQuery<ContextProfileView[], ApiError>({
    queryKey: queryKeys.project.contextProfiles(slug),
    queryFn: ({ signal }) => api.listContextProfiles(slug, { signal }),
    enabled: Boolean(slug),
    ...options,
  });
}

export function useUpdateContextProfile(
  slug: string,
  options?: MutationOpts<ContextProfileView, { kind: AgentKind; body: ContextProfileIn | null }>,
) {
  return useApiMutation<ContextProfileView, { kind: AgentKind; body: ContextProfileIn | null }>(
    ({ kind, body }) => (body ? api.updateContextProfile(slug, kind, body) : api.resetContextProfile(slug, kind)),
    (qc) => inv(qc, queryKeys.project.contextProfiles(slug)),
    options,
  );
}

/* -------------------------------------------------------------------------- */
/* Members                                                                    */
/* -------------------------------------------------------------------------- */

export function useMembers(slug: string, options?: QueryOpts<Member[]>) {
  return useQuery<Member[], ApiError>({
    queryKey: queryKeys.project.members(slug),
    queryFn: ({ signal }) => api.listMembers(slug, { signal }),
    enabled: Boolean(slug),
    ...options,
  });
}

const invalidateMembers = (qc: QueryClient, slug: string) =>
  inv(qc, queryKeys.project.members(slug), queryKeys.project.detail(slug), queryKeys.projects.all());

export function useAddMember(slug: string, options?: MutationOpts<Member, MemberCreateIn>) {
  return useApiMutation<Member, MemberCreateIn>(
    (body) => api.addMember(slug, body),
    (qc) => invalidateMembers(qc, slug),
    options,
  );
}

export function useUpdateMember(slug: string, options?: MutationOpts<Member, { userId: UUID; role: Member["role"] }>) {
  return useApiMutation<Member, { userId: UUID; role: Member["role"] }>(
    ({ userId, role }) => api.updateMember(slug, userId, { role }),
    (qc) => invalidateMembers(qc, slug),
    options,
  );
}

export function useRemoveMember(slug: string, options?: MutationOpts<void, UUID>) {
  return useApiMutation<void, UUID>(
    (userId) => api.removeMember(slug, userId),
    (qc) => invalidateMembers(qc, slug),
    options,
  );
}

/* -------------------------------------------------------------------------- */
/* Agents                                                                     */
/* -------------------------------------------------------------------------- */

export function useAgents(slug: string, options?: QueryOpts<Agent[]>) {
  return useQuery<Agent[], ApiError>({
    queryKey: queryKeys.project.agents(slug),
    queryFn: ({ signal }) => api.listAgents(slug, { signal }),
    enabled: Boolean(slug),
    ...options,
  });
}

export function useCreateAgent(slug: string, options?: MutationOpts<AgentCreated, AgentCreateIn>) {
  return useApiMutation<AgentCreated, AgentCreateIn>(
    (body) => api.createAgent(slug, body),
    (qc) => inv(qc, queryKeys.project.agents(slug)),
    options,
  );
}

export function useRotateAgentKey(slug: string, options?: MutationOpts<AgentCreated, UUID>) {
  return useApiMutation<AgentCreated, UUID>(
    (agentId) => api.rotateAgentKey(slug, agentId),
    (qc) => inv(qc, queryKeys.project.agents(slug)),
    options,
  );
}

export function useRevokeAgent(slug: string, options?: MutationOpts<void, UUID>) {
  return useApiMutation<void, UUID>(
    (agentId) => api.revokeAgent(slug, agentId),
    (qc) => inv(qc, queryKeys.project.agents(slug)),
    options,
  );
}

/* -------------------------------------------------------------------------- */
/* Sources                                                                    */
/* -------------------------------------------------------------------------- */

export function useSources(slug: string, options?: QueryOpts<Source[]>) {
  return useQuery<Source[], ApiError>({
    queryKey: queryKeys.project.sources(slug),
    queryFn: ({ signal }) => api.listSources(slug, { signal }),
    enabled: Boolean(slug),
    ...options,
  });
}

export function useCreateSource(slug: string, options?: MutationOpts<Source, SourceCreateIn>) {
  return useApiMutation<Source, SourceCreateIn>(
    (body) => api.createSource(slug, body),
    (qc) => inv(qc, queryKeys.project.sources(slug), queryKeys.project.overview(slug), queryKeys.projects.all()),
    options,
  );
}

export function useUpdateSource(slug: string, options?: MutationOpts<Source, { id: UUID; body: SourceUpdateIn }>) {
  return useApiMutation<Source, { id: UUID; body: SourceUpdateIn }>(
    ({ id, body }) => api.updateSource(slug, id, body),
    (qc) => inv(qc, queryKeys.project.sources(slug), queryKeys.project.overview(slug)),
    options,
  );
}

/* -------------------------------------------------------------------------- */
/* Documents                                                                  */
/* -------------------------------------------------------------------------- */

const invalidateIngestion = (qc: QueryClient, slug: string) =>
  inv(
    qc,
    queryKeys.project.documents.all(slug),
    queryKeys.project.sources(slug),
    queryKeys.project.jobs.all(slug),
    queryKeys.project.overview(slug),
    queryKeys.projects.all(),
  );

export function useDocuments(
  slug: string,
  params: DocumentListParams = {},
  options?: QueryOpts<Page<DocumentSummary>>,
) {
  return useQuery<Page<DocumentSummary>, ApiError>({
    queryKey: queryKeys.project.documents.list(slug, params),
    queryFn: ({ signal }) => api.listDocuments(slug, params, { signal }),
    enabled: Boolean(slug),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.items.some((d) => ACTIVE_DOC_STATUSES.has(d.status)) ? POLL_MS : false,
    ...options,
  });
}

/** Document detail; polls automatically while the document is pending/processing. */
export function useDocument(slug: string, documentId: UUID | undefined, options?: QueryOpts<DocumentDetail>) {
  return useQuery<DocumentDetail, ApiError>({
    queryKey: queryKeys.project.documents.detail(slug, documentId ?? ""),
    queryFn: ({ signal }) => api.getDocument(slug, documentId as string, { signal }),
    enabled: Boolean(slug && documentId),
    refetchInterval: (query) => {
      const d = query.state.data;
      if (!d) return false;
      const active = ACTIVE_DOC_STATUSES.has(d.status) || d.jobs.some((j) => ACTIVE_JOB_STATUSES.has(j.status));
      return active ? POLL_MS : false;
    },
    ...options,
  });
}

export function useUploadDocuments(slug: string, options?: MutationOpts<DocumentSummary[], DocumentUploadIn>) {
  return useApiMutation<DocumentSummary[], DocumentUploadIn>(
    (input) => api.uploadDocuments(slug, input),
    (qc) => invalidateIngestion(qc, slug),
    options,
  );
}

export function useCreateTextDocument(slug: string, options?: MutationOpts<DocumentSummary, TextDocumentIn>) {
  return useApiMutation<DocumentSummary, TextDocumentIn>(
    (body) => api.createTextDocument(slug, body),
    (qc) => invalidateIngestion(qc, slug),
    options,
  );
}

export function useImportDocuments(slug: string, options?: MutationOpts<DocumentImportResult, DocumentImportIn>) {
  return useApiMutation<DocumentImportResult, DocumentImportIn>(
    (input) => api.importDocuments(slug, input),
    (qc) => invalidateIngestion(qc, slug),
    options,
  );
}

export function useUpdateDocument(
  slug: string,
  options?: MutationOpts<DocumentSummary, { id: UUID; body: DocumentUpdateIn }>,
) {
  return useApiMutation<DocumentSummary, { id: UUID; body: DocumentUpdateIn }>(
    ({ id, body }) => api.updateDocument(slug, id, body),
    (qc) => inv(qc, queryKeys.project.documents.all(slug), queryKeys.project.overview(slug)),
    options,
  );
}

export function useReprocessDocument(slug: string, options?: MutationOpts<Job, UUID>) {
  return useApiMutation<Job, UUID>(
    (documentId) => api.reprocessDocument(slug, documentId),
    (qc) => inv(qc, queryKeys.project.documents.all(slug), queryKeys.project.jobs.all(slug)),
    options,
  );
}

export function useForgetDocument(slug: string, options?: MutationOpts<DocumentSummary, { id: UUID; reason: string }>) {
  return useApiMutation<DocumentSummary, { id: UUID; reason: string }>(
    ({ id, reason }) => api.forgetDocument(slug, id, { reason }),
    (qc) =>
      inv(
        qc,
        queryKeys.project.documents.all(slug),
        queryKeys.project.memory.all(slug),
        queryKeys.project.sources(slug),
        queryKeys.project.snapshots.all(slug),
        queryKeys.project.audit.all(slug),
        queryKeys.project.overview(slug),
        queryKeys.projects.all(),
      ),
    options,
  );
}

/** Downloads the original file (`GET /documents/{id}/raw`) and saves it with `filename`. */
export function useDownloadDocumentRaw(slug: string, options?: MutationOpts<Blob, { id: UUID; filename: string }>) {
  return useApiMutation<Blob, { id: UUID; filename: string }>(
    async ({ id, filename }) => {
      const blob = await api.downloadDocumentRaw(slug, id);
      saveBlob(blob, filename);
      return blob;
    },
    null,
    options,
  );
}

/* -------------------------------------------------------------------------- */
/* Jobs & search                                                              */
/* -------------------------------------------------------------------------- */

/** Jobs list; polls automatically while any job is queued/running. */
export function useJobs(slug: string, params: JobListParams = {}, options?: QueryOpts<Page<JobWithDocument>>) {
  return useQuery<Page<JobWithDocument>, ApiError>({
    queryKey: queryKeys.project.jobs.list(slug, params),
    queryFn: ({ signal }) => api.listJobs(slug, params, { signal }),
    enabled: Boolean(slug),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.items.some((j) => ACTIVE_JOB_STATUSES.has(j.status)) ? POLL_MS : false,
    ...options,
  });
}

/** Hybrid search, enabled when `q` has at least 2 non-blank characters. */
export function useSearch(slug: string | undefined, q: string, limit = 20, options?: QueryOpts<SearchHit[]>) {
  const query = q.trim();
  return useQuery<SearchHit[], ApiError>({
    queryKey: queryKeys.project.search(slug ?? "", query, limit),
    queryFn: ({ signal }) => api.searchProject(slug as string, { q: query, limit }, { signal }),
    enabled: Boolean(slug) && query.length >= 2,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    ...options,
  });
}

/* -------------------------------------------------------------------------- */
/* Memory                                                                     */
/* -------------------------------------------------------------------------- */

const invalidateMemory = (qc: QueryClient, slug: string) =>
  inv(
    qc,
    queryKeys.project.memory.all(slug),
    queryKeys.project.documents.all(slug),
    queryKeys.project.overview(slug),
  );

export function useMemoryList(slug: string, params: MemoryListParams = {}, options?: QueryOpts<Page<MemoryItem>>) {
  return useQuery<Page<MemoryItem>, ApiError>({
    queryKey: queryKeys.project.memory.list(slug, params),
    queryFn: ({ signal }) => api.listMemory(slug, params, { signal }),
    enabled: Boolean(slug),
    placeholderData: keepPreviousData,
    ...options,
  });
}

export function useMemory(slug: string, memoryId: UUID | undefined, options?: QueryOpts<MemoryDetail>) {
  return useQuery<MemoryDetail, ApiError>({
    queryKey: queryKeys.project.memory.detail(slug, memoryId ?? ""),
    queryFn: ({ signal }) => api.getMemory(slug, memoryId as string, { signal }),
    enabled: Boolean(slug && memoryId),
    ...options,
  });
}

export function useMemoryGraph(slug: string, limit = 150, options?: QueryOpts<MemoryGraph>) {
  return useQuery<MemoryGraph, ApiError>({
    queryKey: queryKeys.project.memory.graph(slug, limit),
    queryFn: ({ signal }) => api.getMemoryGraph(slug, { limit }, { signal }),
    enabled: Boolean(slug),
    ...options,
  });
}

export function useSkills(slug: string, options?: QueryOpts<Skill[]>) {
  return useQuery<Skill[], ApiError>({
    queryKey: queryKeys.project.memory.skills(slug),
    queryFn: ({ signal }) => api.listSkills(slug, { signal }),
    enabled: Boolean(slug),
    ...options,
  });
}

export function useEntities(slug: string, options?: QueryOpts<Entity[]>) {
  return useQuery<Entity[], ApiError>({
    queryKey: queryKeys.project.memory.entities(slug),
    queryFn: ({ signal }) => api.listEntities(slug, { signal }),
    enabled: Boolean(slug),
    ...options,
  });
}

export function useEntitySuggestions(slug: string, options?: QueryOpts<EntitySuggestion[]>) {
  return useQuery<EntitySuggestion[], ApiError>({
    queryKey: queryKeys.project.memory.entitySuggestions(slug),
    queryFn: ({ signal }) => api.listEntitySuggestions(slug, { signal }),
    enabled: Boolean(slug),
    ...options,
  });
}

export function useMergeEntity(slug: string) {
  return useApiMutation<Entity, { targetId: UUID; sourceId: UUID }>(
    ({ targetId, sourceId }) => api.mergeEntity(slug, targetId, { source_id: sourceId }),
    (qc) => invalidateMemory(qc, slug),
  );
}

export function useUnmergeEntity(slug: string) {
  return useApiMutation<Entity, UUID>(
    (entityId) => api.unmergeEntity(slug, entityId),
    (qc) => invalidateMemory(qc, slug),
  );
}

export function useReflectMemory(slug: string) {
  return useApiMutation<Job, string | undefined>((month) => api.reflectMemory(slug, month), null);
}

export function useCreateMemory(slug: string, options?: MutationOpts<MemoryItem, MemoryIn>) {
  return useApiMutation<MemoryItem, MemoryIn>(
    (body) => api.createMemory(slug, body),
    (qc) => invalidateMemory(qc, slug),
    options,
  );
}

export function useUpdateMemory(slug: string, options?: MutationOpts<MemoryItem, { id: UUID; body: MemoryUpdateIn }>) {
  return useApiMutation<MemoryItem, { id: UUID; body: MemoryUpdateIn }>(
    ({ id, body }) => api.updateMemory(slug, id, body),
    (qc) => invalidateMemory(qc, slug),
    options,
  );
}

export function useValidateMemory(slug: string, options?: MutationOpts<MemoryItem, { id: UUID; reason?: string }>) {
  return useApiMutation<MemoryItem, { id: UUID; reason?: string }>(
    ({ id, reason }) => api.validateMemory(slug, id, reason ? { reason } : {}),
    (qc) => invalidateMemory(qc, slug),
    options,
  );
}

export function useObsoleteMemory(slug: string, options?: MutationOpts<MemoryItem, { id: UUID; reason: string }>) {
  return useApiMutation<MemoryItem, { id: UUID; reason: string }>(
    ({ id, reason }) => api.obsoleteMemory(slug, id, { reason }),
    (qc) => invalidateMemory(qc, slug),
    options,
  );
}

export function useSupersedeMemory(
  slug: string,
  options?: MutationOpts<MemoryItem, { id: UUID; by_id: UUID; reason?: string }>,
) {
  return useApiMutation<MemoryItem, { id: UUID; by_id: UUID; reason?: string }>(
    ({ id, by_id, reason }) => api.supersedeMemory(slug, id, { by_id, ...(reason ? { reason } : {}) }),
    (qc) => invalidateMemory(qc, slug),
    options,
  );
}

export function useRestoreMemory(slug: string, options?: MutationOpts<MemoryItem, { id: UUID; reason?: string }>) {
  return useApiMutation<MemoryItem, { id: UUID; reason?: string }>(
    ({ id, reason }) => api.restoreMemory(slug, id, reason ? { reason } : {}),
    (qc) => invalidateMemory(qc, slug),
    options,
  );
}

export function useForgetMemory(slug: string, options?: MutationOpts<MemoryItem, { id: UUID; reason: string }>) {
  return useApiMutation<MemoryItem, { id: UUID; reason: string }>(
    ({ id, reason }) => api.forgetMemory(slug, id, { reason }),
    (qc) =>
      inv(
        qc,
        queryKeys.project.memory.all(slug),
        queryKeys.project.documents.all(slug),
        queryKeys.project.snapshots.all(slug),
        queryKeys.project.audit.all(slug),
        queryKeys.project.overview(slug),
      ),
    options,
  );
}

export function useConsolidateMemory(slug: string, options?: MutationOpts<Job, void>) {
  return useApiMutation<Job, void>(
    () => api.consolidateMemory(slug),
    (qc) => inv(qc, queryKeys.project.jobs.all(slug), queryKeys.project.memory.all(slug)),
    options,
  );
}

/* -------------------------------------------------------------------------- */
/* Sessions                                                                   */
/* -------------------------------------------------------------------------- */

export function useSessions(slug: string, options?: QueryOpts<SessionSummary[]>) {
  return useQuery<SessionSummary[], ApiError>({
    queryKey: queryKeys.project.sessions.list(slug),
    queryFn: ({ signal }) => api.listSessions(slug, { signal }),
    enabled: Boolean(slug),
    ...options,
  });
}

export function useSession(slug: string, sessionId: string | undefined, options?: QueryOpts<SessionDetail>) {
  return useQuery<SessionDetail, ApiError>({
    queryKey: queryKeys.project.sessions.detail(slug, sessionId ?? ""),
    queryFn: ({ signal }) => api.getSession(slug, sessionId as string, { signal }),
    enabled: Boolean(slug && sessionId),
    ...options,
  });
}

export function useAddSessionTurn(
  slug: string,
  options?: MutationOpts<SessionTurnResult, { sessionId: string; body: SessionTurnIn }>,
) {
  return useApiMutation<SessionTurnResult, { sessionId: string; body: SessionTurnIn }>(
    ({ sessionId, body }) => api.addSessionTurn(slug, sessionId, body),
    (qc) => inv(qc, queryKeys.project.sessions.all(slug)),
    options,
  );
}

export function useCloseSession(slug: string, options?: MutationOpts<SessionCloseResult, string>) {
  return useApiMutation<SessionCloseResult, string>(
    (sessionId) => api.closeSession(slug, sessionId),
    (qc) => inv(qc, queryKeys.project.sessions.all(slug), queryKeys.project.memory.all(slug)),
    options,
  );
}

/* -------------------------------------------------------------------------- */
/* Context                                                                    */
/* -------------------------------------------------------------------------- */

export function useAssembleContext(slug: string, options?: MutationOpts<ContextPackage, ContextRequestIn>) {
  return useApiMutation<ContextPackage, ContextRequestIn>(
    (body) => api.assembleContext(slug, body),
    (qc, pkg) => {
      qc.setQueryData<ContextRequestDetail>(queryKeys.project.context.request(slug, pkg.request_id), {
        ...pkg,
        feedback: [],
      });
      return inv(
        qc,
        queryKeys.project.context.all(slug),
        queryKeys.project.metrics(slug),
        queryKeys.project.overview(slug),
        queryKeys.project.snapshots.all(slug),
        queryKeys.project.audit.all(slug),
      );
    },
    options,
  );
}

export function useContextRequests(
  slug: string,
  params: ContextRequestListParams = {},
  options?: QueryOpts<Page<ContextRequestSummary>>,
) {
  return useQuery<Page<ContextRequestSummary>, ApiError>({
    queryKey: queryKeys.project.context.requests(slug, params),
    queryFn: ({ signal }) => api.listContextRequests(slug, params, { signal }),
    enabled: Boolean(slug),
    placeholderData: keepPreviousData,
    ...options,
  });
}

export function useContextRequest(slug: string, requestId: UUID | undefined, options?: QueryOpts<ContextRequestDetail>) {
  return useQuery<ContextRequestDetail, ApiError>({
    queryKey: queryKeys.project.context.request(slug, requestId ?? ""),
    queryFn: ({ signal }) => api.getContextRequest(slug, requestId as string, { signal }),
    enabled: Boolean(slug && requestId),
    ...options,
  });
}

export function useSendContextFeedback(
  slug: string,
  options?: MutationOpts<CreatedId, { requestId: UUID; body: ContextFeedbackIn }>,
) {
  return useApiMutation<CreatedId, { requestId: UUID; body: ContextFeedbackIn }>(
    ({ requestId, body }) => api.sendContextFeedback(slug, requestId, body),
    (qc) =>
      inv(
        qc,
        queryKeys.project.context.all(slug),
        queryKeys.project.metrics(slug),
        queryKeys.project.memory.all(slug),
      ),
    options,
  );
}

/* -------------------------------------------------------------------------- */
/* Snapshots                                                                  */
/* -------------------------------------------------------------------------- */

export function useSnapshots(slug: string, options?: QueryOpts<SnapshotListItem[]>) {
  return useQuery<SnapshotListItem[], ApiError>({
    queryKey: queryKeys.project.snapshots.list(slug),
    queryFn: ({ signal }) => api.listSnapshots(slug, { signal }),
    enabled: Boolean(slug),
    ...options,
  });
}

export function useSnapshotVersions(slug: string, name: string | undefined, options?: QueryOpts<SnapshotSummary[]>) {
  return useQuery<SnapshotSummary[], ApiError>({
    queryKey: queryKeys.project.snapshots.versions(slug, name ?? ""),
    queryFn: ({ signal }) => api.listSnapshotVersions(slug, name as string, { signal }),
    enabled: Boolean(slug && name),
    ...options,
  });
}

export function useSnapshot(
  slug: string,
  name: string | undefined,
  version: SnapshotVersionRef = "latest",
  options?: QueryOpts<Snapshot>,
) {
  return useQuery<Snapshot, ApiError>({
    queryKey: queryKeys.project.snapshots.detail(slug, name ?? "", version),
    queryFn: ({ signal }) => api.getSnapshot(slug, name as string, version, { signal }),
    enabled: Boolean(slug && name),
    // Numbered versions are immutable.
    staleTime: version === "latest" ? 30_000 : Infinity,
    ...options,
  });
}

export function useSnapshotDiff(
  slug: string,
  name: string | undefined,
  from: number | undefined,
  to: number | undefined,
  options?: QueryOpts<SnapshotDiff>,
) {
  return useQuery<SnapshotDiff, ApiError>({
    queryKey: queryKeys.project.snapshots.diff(slug, name ?? "", from ?? 0, to ?? 0),
    queryFn: ({ signal }) =>
      api.diffSnapshot(slug, name as string, { from: from as number, to: to as number }, { signal }),
    enabled: Boolean(slug && name && from && to && from !== to),
    ...options,
  });
}

/* -------------------------------------------------------------------------- */
/* Observability & audit                                                      */
/* -------------------------------------------------------------------------- */

export function useMetrics(slug: string, days = 14, options?: QueryOpts<Metrics>) {
  return useQuery<Metrics, ApiError>({
    queryKey: queryKeys.project.metrics(slug, days),
    queryFn: ({ signal }) => api.getMetrics(slug, { days }, { signal }),
    enabled: Boolean(slug),
    placeholderData: keepPreviousData,
    ...options,
  });
}

export function useAudit(slug: string, params: AuditListParams = {}, options?: QueryOpts<Page<AuditEvent>>) {
  return useQuery<Page<AuditEvent>, ApiError>({
    queryKey: queryKeys.project.audit.list(slug, params),
    queryFn: ({ signal }) => api.listAudit(slug, params, { signal }),
    enabled: Boolean(slug),
    placeholderData: keepPreviousData,
    ...options,
  });
}

/** Downloads the NDJSON trace export (owner) as `orbit-traces-<slug>-<days>j.ndjson`. */
export function useExportTraces(slug: string, options?: MutationOpts<string, { days?: number } | void>) {
  return useApiMutation<string, { days?: number } | void>(
    async (vars) => {
      const days = (vars && vars.days) || 30;
      const text = await api.exportTraces(slug, { days });
      saveBlob(new Blob([text], { type: "application/x-ndjson" }), `orbit-traces-${slug}-${days}j.ndjson`);
      return text;
    },
    null,
    options,
  );
}

/* -------------------------------------------------------------------------- */
/* System                                                                     */
/* -------------------------------------------------------------------------- */

export function useMeta(options?: QueryOpts<Meta>) {
  return useQuery<Meta, ApiError>({
    queryKey: queryKeys.meta(),
    queryFn: ({ signal }) => api.getMeta({ signal }),
    staleTime: 10 * 60_000,
    retry: 1,
    ...options,
  });
}
