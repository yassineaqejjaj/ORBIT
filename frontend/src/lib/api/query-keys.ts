/**
 * Query-key factory. Every project-scoped key starts with `["orbit", "project", slug]`,
 * so `invalidateQueries({ queryKey: queryKeys.project.all(slug) })` refreshes a whole project.
 */
import type {
  AuditListParams,
  ContextRequestListParams,
  DocumentListParams,
  JobListParams,
  MemoryListParams,
  SnapshotVersionRef,
  UserListParams,
} from "./types";

const ROOT = "orbit" as const;

const projectRoot = (slug: string) => [ROOT, "project", slug] as const;

export const queryKeys = {
  all: [ROOT] as const,
  me: () => [ROOT, "me"] as const,
  meta: () => [ROOT, "meta"] as const,
  authConfig: () => [ROOT, "auth-config"] as const,

  account: {
    all: () => [ROOT, "account"] as const,
    sessions: () => [ROOT, "account", "sessions"] as const,
    delegations: () => [ROOT, "account", "delegations"] as const,
    /** User-scope memory of the caller, aggregated over projects. */
    memory: (projectIds: readonly string[]) => [ROOT, "account", "memory", [...projectIds]] as const,
  },

  compliance: {
    all: () => [ROOT, "compliance"] as const,
    retention: () => [ROOT, "compliance", "retention"] as const,
    auditVerify: () => [ROOT, "compliance", "audit-verify"] as const,
    register: () => [ROOT, "compliance", "processing-register"] as const,
  },

  ops: {
    all: () => [ROOT, "ops"] as const,
    status: () => [ROOT, "ops", "status"] as const,
    deadLetter: () => [ROOT, "ops", "dead-letter"] as const,
    drift: (project: string | undefined) => [ROOT, "ops", "drift", project ?? null] as const,
  },

  users: {
    all: () => [ROOT, "users"] as const,
    list: (params: UserListParams = {}) => [ROOT, "users", "list", params] as const,
  },

  projects: {
    all: () => [ROOT, "projects"] as const,
    list: () => [ROOT, "projects", "list"] as const,
  },

  project: {
    all: projectRoot,
    detail: (slug: string) => [...projectRoot(slug), "detail"] as const,
    overview: (slug: string) => [...projectRoot(slug), "overview"] as const,
    members: (slug: string) => [...projectRoot(slug), "members"] as const,
    agents: (slug: string) => [...projectRoot(slug), "agents"] as const,
    sources: (slug: string) => [...projectRoot(slug), "sources"] as const,

    documents: {
      all: (slug: string) => [...projectRoot(slug), "documents"] as const,
      list: (slug: string, params: DocumentListParams = {}) =>
        [...projectRoot(slug), "documents", "list", params] as const,
      detail: (slug: string, id: string) => [...projectRoot(slug), "documents", "detail", id] as const,
    },

    jobs: {
      all: (slug: string) => [...projectRoot(slug), "jobs"] as const,
      list: (slug: string, params: JobListParams = {}) => [...projectRoot(slug), "jobs", "list", params] as const,
    },

    search: (slug: string, q: string, limit?: number) =>
      [...projectRoot(slug), "search", { q, limit: limit ?? null }] as const,

    memory: {
      all: (slug: string) => [...projectRoot(slug), "memory"] as const,
      list: (slug: string, params: MemoryListParams = {}) =>
        [...projectRoot(slug), "memory", "list", params] as const,
      detail: (slug: string, id: string) => [...projectRoot(slug), "memory", "detail", id] as const,
      graph: (slug: string, limit?: number) =>
        [...projectRoot(slug), "memory", "graph", { limit: limit ?? null }] as const,
    },

    sessions: {
      all: (slug: string) => [...projectRoot(slug), "sessions"] as const,
      list: (slug: string) => [...projectRoot(slug), "sessions", "list"] as const,
      detail: (slug: string, sessionId: string) => [...projectRoot(slug), "sessions", "detail", sessionId] as const,
    },

    context: {
      all: (slug: string) => [...projectRoot(slug), "context"] as const,
      requests: (slug: string, params: ContextRequestListParams = {}) =>
        [...projectRoot(slug), "context", "requests", params] as const,
      request: (slug: string, id: string) => [...projectRoot(slug), "context", "request", id] as const,
    },

    snapshots: {
      all: (slug: string) => [...projectRoot(slug), "snapshots"] as const,
      list: (slug: string) => [...projectRoot(slug), "snapshots", "list"] as const,
      versions: (slug: string, name: string) => [...projectRoot(slug), "snapshots", "versions", name] as const,
      detail: (slug: string, name: string, version: SnapshotVersionRef) =>
        [...projectRoot(slug), "snapshots", "detail", name, String(version)] as const,
      diff: (slug: string, name: string, from: number, to: number) =>
        [...projectRoot(slug), "snapshots", "diff", name, { from, to }] as const,
    },

    metrics: (slug: string, days?: number) => [...projectRoot(slug), "metrics", { days: days ?? null }] as const,

    audit: {
      all: (slug: string) => [...projectRoot(slug), "audit"] as const,
      list: (slug: string, params: AuditListParams = {}) => [...projectRoot(slug), "audit", "list", params] as const,
    },
  },
} as const;
