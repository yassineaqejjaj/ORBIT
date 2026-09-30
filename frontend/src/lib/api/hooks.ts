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

import { isSignedInUser } from "@/lib/auth/login-result";

import { resetCsrfToken, saveBlob, type ApiError } from "./client";
import * as api from "./endpoints";
import { queryKeys } from "./query-keys";
import type {
  AccountSession,
  AgentDelegation,
  AuditVerifyResult,
  AuthConfig,
  DeadLetterJob,
  DelegationCreateIn,
  DriftReport,
  ErasureResult,
  InvitationCreated,
  InvitationIn,
  LoginResult,
  MfaDisableIn,
  MfaRecoveryCodes,
  MfaSetup,
  OpsStatus,
  PasswordChangeIn,
  PersonalDataExport,
  ProcessingRegister,
  ReindexIn,
  RetentionState,
  RetentionUpdateIn,
  TemporaryPassword,
  Agent,
  AgentCreateIn,
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

/** Drop every cached query of the previous identity and store the new one. */
function onSignedIn(qc: QueryClient, user: User): void {
  resetCsrfToken();
  qc.removeQueries({ predicate: (q) => q.queryKey[0] === "orbit" && q.queryKey[1] !== "me" && q.queryKey[1] !== "auth-config" });
  qc.setQueryData(queryKeys.me(), user);
}

/** Step 1 of the login: may return the User or an MFA / password-change challenge. */
export function useLogin(options?: MutationOpts<LoginResult, LoginIn>) {
  return useApiMutation<LoginResult, LoginIn>(
    api.login,
    (qc, result) => {
      if (isSignedInUser(result)) onSignedIn(qc, result);
    },
    { meta: { silentError: true }, ...options },
  );
}

/** Public login options (`GET /auth/config`). */
export function useAuthConfig(options?: QueryOpts<AuthConfig>) {
  return useQuery<AuthConfig, ApiError>({
    queryKey: queryKeys.authConfig(),
    queryFn: ({ signal }) => api.getAuthConfig({ signal }),
    staleTime: 10 * 60_000,
    retry: 1,
    ...options,
  });
}

/** Step 2 (MFA): TOTP or recovery code. */
export function useVerifyMfa(options?: MutationOpts<User, { mfa_token: string; code: string }>) {
  return useApiMutation<User, { mfa_token: string; code: string }>(
    api.verifyMfa,
    (qc, user) => onSignedIn(qc, user),
    { meta: { silentError: true }, ...options },
  );
}

/** Step 2 (alternative): forced password change before the session is opened. */
export function useChangeRequiredPassword(options?: MutationOpts<User, { change_token: string; new_password: string }>) {
  return useApiMutation<User, { change_token: string; new_password: string }>(
    api.changeRequiredPassword,
    (qc, user) => onSignedIn(qc, user),
    { meta: { silentError: true }, ...options },
  );
}

/** Invitation acceptance (`/invitation/[token]`): sets the password and signs in. */
export function useAcceptInvitation(options?: MutationOpts<User, { token: string; password: string }>) {
  return useApiMutation<User, { token: string; password: string }>(
    ({ token, password }) => api.acceptInvitation(token, { password }),
    (qc, user) => onSignedIn(qc, user),
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
      resetCsrfToken();
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

/* -------------------------------------------------------------------------- */
/* Account (docs/PRODUCTION.md §3)                                            */
/* -------------------------------------------------------------------------- */

export function useAccountSessions(options?: QueryOpts<AccountSession[]>) {
  return useQuery<AccountSession[], ApiError>({
    queryKey: queryKeys.account.sessions(),
    queryFn: ({ signal }) => api.listAccountSessions({ signal }),
    ...options,
  });
}

export function useRevokeAccountSession(options?: MutationOpts<void, UUID>) {
  return useApiMutation<void, UUID>(api.revokeAccountSession, (qc) => inv(qc, queryKeys.account.sessions()), options);
}

export function useChangePassword(options?: MutationOpts<void, PasswordChangeIn>) {
  return useApiMutation<void, PasswordChangeIn>(
    api.changePassword,
    (qc) => inv(qc, queryKeys.account.sessions(), queryKeys.me()),
    { meta: { silentError: true }, ...options },
  );
}

export function useSetupMfa(options?: MutationOpts<MfaSetup, void>) {
  return useApiMutation<MfaSetup, void>(() => api.setupMfa(), null, { meta: { silentError: true }, ...options });
}

export function useEnableMfa(options?: MutationOpts<MfaRecoveryCodes, string>) {
  return useApiMutation<MfaRecoveryCodes, string>(
    (code) => api.enableMfa({ code }),
    (qc) => inv(qc, queryKeys.me()),
    { meta: { silentError: true }, ...options },
  );
}

export function useDisableMfa(options?: MutationOpts<void, MfaDisableIn>) {
  return useApiMutation<void, MfaDisableIn>(api.disableMfa, (qc) => inv(qc, queryKeys.me()), {
    meta: { silentError: true },
    ...options,
  });
}

/** Save a JSON document as a file. */
function saveJson(data: unknown, filename: string): void {
  saveBlob(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }), filename);
}

/** Downloads `GET /account/export` as `orbit-mes-donnees-<date>.json`. */
export function useExportMyData(options?: MutationOpts<PersonalDataExport, void>) {
  return useApiMutation<PersonalDataExport, void>(
    async () => {
      const data = await api.exportMyData();
      saveJson(data, `orbit-mes-donnees-${new Date().toISOString().slice(0, 10)}.json`);
      return data;
    },
    null,
    options,
  );
}

export function useMyDelegations(options?: QueryOpts<AgentDelegation[]>) {
  return useQuery<AgentDelegation[], ApiError>({
    queryKey: queryKeys.account.delegations(),
    queryFn: ({ signal }) => api.listMyDelegations({ signal }),
    ...options,
  });
}

export function useCreateDelegation(options?: MutationOpts<AgentDelegation, { slug: string; body: DelegationCreateIn }>) {
  return useApiMutation<AgentDelegation, { slug: string; body: DelegationCreateIn }>(
    ({ slug, body }) => api.createDelegation(slug, body),
    (qc) => inv(qc, queryKeys.account.delegations()),
    options,
  );
}

export function useRevokeDelegation(options?: MutationOpts<void, { slug: string; id: UUID }>) {
  return useApiMutation<void, { slug: string; id: UUID }>(
    ({ slug, id }) => api.revokeDelegation(slug, id),
    (qc) => inv(qc, queryKeys.account.delegations()),
    options,
  );
}

/** A user-scope memory item of the caller, with the project it belongs to. */
export type MyMemoryItem = MemoryItem & { project: Pick<ProjectSummary, "id" | "slug" | "name"> };

/**
 * User-scope memory about the caller across every project they belong to ("Mes données").
 * The API only returns user-scope items to their subject; the filter on `subject_user_id` is a safeguard.
 */
export function useMyUserMemory(
  projects: ReadonlyArray<Pick<ProjectSummary, "id" | "slug" | "name">> | undefined,
  userId: UUID | undefined,
  options?: QueryOpts<MyMemoryItem[]>,
) {
  const list = projects ?? [];
  return useQuery<MyMemoryItem[], ApiError>({
    queryKey: queryKeys.account.memory(list.map((p) => p.id)),
    queryFn: async ({ signal }) => {
      const pages = await Promise.all(
        list.map(async (project) => {
          const page = await api.listMemory(project.slug, { scope: "user", page_size: 100 }, { signal });
          return page.items
            .filter((item) => item.subject_user_id === userId)
            .map((item) => ({ ...item, project: { id: project.id, slug: project.slug, name: project.name } }));
        }),
      );
      return pages.flat().sort((a, b) => b.created_at.localeCompare(a.created_at));
    },
    enabled: Boolean(projects && userId),
    ...options,
  });
}

/* -------------------------------------------------------------------------- */
/* Admin — user lifecycle                                                     */
/* -------------------------------------------------------------------------- */

const invUsers = (qc: QueryClient) => inv(qc, queryKeys.users.all());

export function useDeactivateUser(options?: MutationOpts<User, UUID>) {
  return useApiMutation<User, UUID>(api.deactivateUser, invUsers, options);
}

export function useReactivateUser(options?: MutationOpts<User, UUID>) {
  return useApiMutation<User, UUID>(api.reactivateUser, invUsers, options);
}

export function useResetUserPassword(options?: MutationOpts<TemporaryPassword, UUID>) {
  return useApiMutation<TemporaryPassword, UUID>(api.resetUserPassword, invUsers, options);
}

export function useResetUserMfa(options?: MutationOpts<User, UUID>) {
  return useApiMutation<User, UUID>(api.resetUserMfa, invUsers, options);
}

export function useInviteUser(options?: MutationOpts<InvitationCreated, InvitationIn>) {
  return useApiMutation<InvitationCreated, InvitationIn>(api.inviteUser, invUsers, options);
}

/* -------------------------------------------------------------------------- */
/* Compliance                                                                 */
/* -------------------------------------------------------------------------- */

/** Downloads the personal data export of a user (admin DSAR). */
export function useExportUserData(options?: MutationOpts<PersonalDataExport, { id: UUID; email: string }>) {
  return useApiMutation<PersonalDataExport, { id: UUID; email: string }>(
    async ({ id, email }) => {
      const data = await api.exportUserData(id);
      const safe = email.replace(/[^a-z0-9._-]+/gi, "_");
      saveJson(data, `orbit-export-${safe}-${new Date().toISOString().slice(0, 10)}.json`);
      return data;
    },
    null,
    options,
  );
}

export function useEraseUser(options?: MutationOpts<ErasureResult, { id: UUID; reason: string }>) {
  return useApiMutation<ErasureResult, { id: UUID; reason: string }>(
    ({ id, reason }) => api.eraseUser(id, { reason }),
    (qc) => inv(qc, queryKeys.users.all(), queryKeys.projects.all()),
    options,
  );
}

export function useArchiveProject(slug: string, options?: MutationOpts<Project, string>) {
  return useApiMutation<Project, string>(
    (confirmSlug) => api.archiveProject(slug, { confirm_slug: confirmSlug }),
    (qc) => inv(qc, queryKeys.project.all(slug), queryKeys.projects.all()),
    options,
  );
}

export function useDeleteProject(slug: string, options?: MutationOpts<Job | undefined, string>) {
  return useApiMutation<Job | undefined, string>(
    (confirmSlug) => api.deleteProject(slug, { confirm_slug: confirmSlug }),
    (qc) => {
      qc.removeQueries({ queryKey: queryKeys.project.all(slug) });
      return inv(qc, queryKeys.projects.all());
    },
    options,
  );
}

export function useRetention(options?: QueryOpts<RetentionState>) {
  return useQuery<RetentionState, ApiError>({
    queryKey: queryKeys.compliance.retention(),
    queryFn: ({ signal }) => api.getRetention({ signal }),
    ...options,
  });
}

export function useUpdateRetention(options?: MutationOpts<RetentionState, RetentionUpdateIn>) {
  return useApiMutation<RetentionState, RetentionUpdateIn>(
    api.updateRetention,
    (qc) => inv(qc, queryKeys.compliance.retention()),
    options,
  );
}

/** On-demand verification of the chained audit log (button-triggered). */
export function useVerifyAuditChain(options?: MutationOpts<AuditVerifyResult, void>) {
  return useApiMutation<AuditVerifyResult, void>(() => api.verifyAuditChain(), null, {
    meta: { silentError: true },
    ...options,
  });
}

export function useProcessingRegister(options?: QueryOpts<ProcessingRegister>) {
  return useQuery<ProcessingRegister, ApiError>({
    queryKey: queryKeys.compliance.register(),
    queryFn: ({ signal }) => api.getProcessingRegister({ signal }),
    staleTime: 5 * 60_000,
    ...options,
  });
}

/* -------------------------------------------------------------------------- */
/* Operations                                                                 */
/* -------------------------------------------------------------------------- */

const OPS_POLL_MS = 15_000;

export function useOpsStatus(options?: QueryOpts<OpsStatus>) {
  return useQuery<OpsStatus, ApiError>({
    queryKey: queryKeys.ops.status(),
    queryFn: ({ signal }) => api.getOpsStatus({ signal }),
    refetchInterval: OPS_POLL_MS,
    ...options,
  });
}

/** Dead-letter jobs, normalized to a list whatever the envelope (list or page). */
export function useDeadLetterJobs(options?: QueryOpts<DeadLetterJob[]>) {
  return useQuery<DeadLetterJob[], ApiError>({
    queryKey: queryKeys.ops.deadLetter(),
    queryFn: async ({ signal }) => {
      const data = await api.listDeadLetterJobs({ signal });
      return Array.isArray(data) ? data : (data?.items ?? []);
    },
    refetchInterval: OPS_POLL_MS,
    ...options,
  });
}

export function useIndexDrift(project: string | undefined, options?: QueryOpts<DriftReport>) {
  return useQuery<DriftReport, ApiError>({
    queryKey: queryKeys.ops.drift(project),
    queryFn: ({ signal }) => api.getIndexDrift(project, { signal }),
    ...options,
  });
}

export function useStartReindex(options?: MutationOpts<Job, ReindexIn>) {
  return useApiMutation<Job, ReindexIn>(
    api.startReindex,
    (qc, _job, vars) =>
      inv(qc, queryKeys.ops.all(), ...(vars.project_slug ? [queryKeys.project.jobs.all(vars.project_slug)] : [])),
    options,
  );
}

const invJobs = (qc: QueryClient, slug: string) =>
  inv(qc, queryKeys.project.jobs.all(slug), queryKeys.project.documents.all(slug), queryKeys.ops.deadLetter(), queryKeys.ops.status());

export function useRetryJob(options?: MutationOpts<Job, { slug: string; jobId: UUID }>) {
  return useApiMutation<Job, { slug: string; jobId: UUID }>(
    ({ slug, jobId }) => api.retryJob(slug, jobId),
    (qc, _job, { slug }) => invJobs(qc, slug),
    options,
  );
}

export function useCancelJob(options?: MutationOpts<Job, { slug: string; jobId: UUID }>) {
  return useApiMutation<Job, { slug: string; jobId: UUID }>(
    ({ slug, jobId }) => api.cancelJob(slug, jobId),
    (qc, _job, { slug }) => invJobs(qc, slug),
    options,
  );
}
