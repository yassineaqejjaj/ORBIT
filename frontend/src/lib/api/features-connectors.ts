"use client";

/**
 * F5 (connecteurs SharePoint, Confluence, Jira + assistant de démarrage): types, endpoint functions and
 * TanStack Query hooks — see docs/FEATURES.md. Secrets are write-only: the API only returns a masked hint.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http, type ApiError } from "./client";
import { queryKeys } from "./query-keys";
import type { ISODateString, Page, UUID } from "./types";

/* -------------------------------------------------------------------------- */
/* Types                                                                      */
/* -------------------------------------------------------------------------- */

export type ConnectorType = "sharepoint" | "confluence" | "jira";
export type ConnectorStatus = "idle" | "syncing" | "ok" | "error" | "paused";
export type ConnectorRunStatus = "queued" | "running" | "succeeded" | "partial" | "failed";
export type ConnectorRunTrigger = "manual" | "schedule" | "initial";

/** Non-secret configuration (shape depends on the type). */
export interface ConnectorConfig {
  // SharePoint
  tenant_id?: string;
  client_id?: string;
  site_ids?: string[];
  drive_ids?: string[];
  // Confluence / Jira
  base_url?: string;
  deployment?: "cloud" | "datacenter";
  email?: string;
  space_keys?: string[];
  jql?: string;
  /** Display names of the chosen scope (sites, libraries, spaces). */
  scope_labels?: string[];
}

export interface ConnectorRun {
  id: UUID;
  connector_id: UUID;
  trigger: ConnectorRunTrigger;
  status: ConnectorRunStatus;
  started_at: ISODateString | null;
  finished_at: ISODateString | null;
  duration_ms: number | null;
  fetched: number;
  created: number;
  updated: number;
  unchanged: number;
  skipped: number;
  forgotten: number;
  errors: number;
  progress: { phase?: string; message?: string; fetched?: number };
  error_samples: { item: string; error: string }[];
  error: string | null;
  created_at: ISODateString;
}

export interface Connector {
  id: UUID;
  type: ConnectorType;
  type_label: string;
  name: string;
  config: ConnectorConfig;
  has_secret: boolean;
  secret_hint: string;
  schedule_minutes: number;
  status: ConnectorStatus;
  paused: boolean;
  default_classification: number;
  restrict_to_editors: boolean;
  acl_principals: string[];
  last_sync_at: ISODateString | null;
  last_error: string | null;
  source_id: UUID | null;
  document_count: number;
  last_run: ConnectorRun | null;
  suggested_task: string;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface ConnectorIn {
  type: ConnectorType;
  name: string;
  config: ConnectorConfig;
  secret: string;
  schedule_minutes?: number;
  default_classification?: number;
  restrict_to_editors?: boolean;
  start_sync?: boolean;
}

export interface ConnectorPatch {
  name?: string;
  config?: ConnectorConfig;
  secret?: string;
  schedule_minutes?: number;
  default_classification?: number;
  restrict_to_editors?: boolean;
  paused?: boolean;
}

export interface ScopeOption {
  id: string;
  label: string;
  kind: "site" | "drive" | "space" | "project" | string;
  parent_id: string | null;
  description: string;
}

export interface ConnectorTestResult {
  ok: boolean;
  message: string;
  account: string | null;
  scope_options: ScopeOption[];
  duration_ms: number;
}

export interface ConnectorTestIn {
  type: ConnectorType;
  config: ConnectorConfig;
  secret: string;
}

export const ACTIVE_RUN_STATUSES: readonly ConnectorRunStatus[] = ["queued", "running"];

export function isRunActive(run: ConnectorRun | null | undefined): boolean {
  return Boolean(run && ACTIVE_RUN_STATUSES.includes(run.status));
}

/* -------------------------------------------------------------------------- */
/* Endpoints                                                                  */
/* -------------------------------------------------------------------------- */

type Opts = { signal?: AbortSignal };
const e = encodeURIComponent;
const c = (slug: string) => `/projects/${e(slug)}/connectors`;

export const featuresConnectorsApi = {
  list: (slug: string, opts: Opts = {}) => http.get<Connector[]>(c(slug), opts),
  get: (slug: string, id: UUID, opts: Opts = {}) => http.get<Connector>(`${c(slug)}/${e(id)}`, opts),
  create: (slug: string, body: ConnectorIn) => http.post<Connector>(c(slug), body),
  update: (slug: string, id: UUID, body: ConnectorPatch) => http.patch<Connector>(`${c(slug)}/${e(id)}`, body),
  remove: (slug: string, id: UUID) => http.delete(`${c(slug)}/${e(id)}`),
  testCredentials: (slug: string, body: ConnectorTestIn) => http.post<ConnectorTestResult>(`${c(slug)}/test`, body),
  testSaved: (slug: string, id: UUID, body: { config?: ConnectorConfig; secret?: string } = {}) =>
    http.post<ConnectorTestResult>(`${c(slug)}/${e(id)}/test`, body),
  sync: (slug: string, id: UUID) => http.post<ConnectorRun>(`${c(slug)}/${e(id)}/sync`),
  runs: (slug: string, id: UUID, page = 1, opts: Opts = {}) =>
    http.get<Page<ConnectorRun>>(`${c(slug)}/${e(id)}/runs`, { query: { page, page_size: 20 }, ...opts }),
  run: (slug: string, id: UUID, runId: UUID, opts: Opts = {}) =>
    http.get<ConnectorRun>(`${c(slug)}/${e(id)}/runs/${e(runId)}`, opts),
};

/* -------------------------------------------------------------------------- */
/* Query keys & hooks                                                         */
/* -------------------------------------------------------------------------- */

const root = (slug: string) => [...queryKeys.project.all(slug), "features-connectors"] as const;

export const featuresConnectorsKeys = {
  all: root,
  list: (slug: string) => [...root(slug), "list"] as const,
  detail: (slug: string, id: UUID) => [...root(slug), "detail", id] as const,
  runs: (slug: string, id: UUID, page: number) => [...root(slug), "runs", id, page] as const,
  run: (slug: string, id: UUID, runId: UUID) => [...root(slug), "run", id, runId] as const,
};

const POLL_ACTIVE_MS = 2_000;
const POLL_IDLE_MS = 60_000;

export function useConnectors(slug: string) {
  return useQuery<Connector[], ApiError>({
    queryKey: featuresConnectorsKeys.list(slug),
    queryFn: ({ signal }) => featuresConnectorsApi.list(slug, { signal }),
    enabled: Boolean(slug),
    refetchInterval: (query) =>
      query.state.data?.some((connector) => isRunActive(connector.last_run)) ? POLL_ACTIVE_MS : POLL_IDLE_MS,
  });
}

export function useConnector(slug: string, id: UUID | null) {
  return useQuery<Connector, ApiError>({
    queryKey: featuresConnectorsKeys.detail(slug, id ?? ""),
    queryFn: ({ signal }) => featuresConnectorsApi.get(slug, id as string, { signal }),
    enabled: Boolean(slug && id),
    refetchInterval: (query) => (isRunActive(query.state.data?.last_run) ? POLL_ACTIVE_MS : false),
  });
}

export function useConnectorRuns(slug: string, id: UUID | null, page = 1, live = false) {
  return useQuery<Page<ConnectorRun>, ApiError>({
    queryKey: featuresConnectorsKeys.runs(slug, id ?? "", page),
    queryFn: ({ signal }) => featuresConnectorsApi.runs(slug, id as string, page, { signal }),
    enabled: Boolean(slug && id),
    placeholderData: keepPreviousData,
    refetchInterval: live ? POLL_ACTIVE_MS : false,
  });
}

/** Live progress of one run (wizard step 4): polls every 1.5 s until it finishes. */
export function useConnectorRun(slug: string, id: UUID | null, runId: UUID | null) {
  return useQuery<ConnectorRun, ApiError>({
    queryKey: featuresConnectorsKeys.run(slug, id ?? "", runId ?? ""),
    queryFn: ({ signal }) => featuresConnectorsApi.run(slug, id as string, runId as string, { signal }),
    enabled: Boolean(slug && id && runId),
    refetchInterval: (query) => (query.state.data && !isRunActive(query.state.data) ? false : 1_500),
  });
}

function useInvalidateConnectors(slug: string) {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: featuresConnectorsKeys.all(slug) });
}

export function useCreateConnector(slug: string) {
  const invalidate = useInvalidateConnectors(slug);
  return useMutation<Connector, ApiError, ConnectorIn>({
    mutationFn: (body) => featuresConnectorsApi.create(slug, body),
    onSuccess: () => invalidate(),
    meta: { silentError: true },
  });
}

export function useUpdateConnector(slug: string) {
  const invalidate = useInvalidateConnectors(slug);
  return useMutation<Connector, ApiError, { id: UUID } & ConnectorPatch>({
    mutationFn: ({ id, ...body }) => featuresConnectorsApi.update(slug, id, body),
    onSuccess: () => invalidate(),
    meta: { silentError: true },
  });
}

export function useDeleteConnector(slug: string) {
  const invalidate = useInvalidateConnectors(slug);
  return useMutation<unknown, ApiError, UUID>({
    mutationFn: (id) => featuresConnectorsApi.remove(slug, id),
    onSuccess: () => invalidate(),
  });
}

export function useTestConnectorCredentials(slug: string) {
  return useMutation<ConnectorTestResult, ApiError, ConnectorTestIn>({
    mutationFn: (body) => featuresConnectorsApi.testCredentials(slug, body),
    meta: { silentError: true },
  });
}

export function useTestSavedConnector(slug: string) {
  return useMutation<ConnectorTestResult, ApiError, { id: UUID; config?: ConnectorConfig; secret?: string }>({
    mutationFn: ({ id, ...body }) => featuresConnectorsApi.testSaved(slug, id, body),
  });
}

export function useSyncConnector(slug: string) {
  const invalidate = useInvalidateConnectors(slug);
  return useMutation<ConnectorRun, ApiError, UUID>({
    mutationFn: (id) => featuresConnectorsApi.sync(slug, id),
    onSuccess: () => invalidate(),
  });
}
