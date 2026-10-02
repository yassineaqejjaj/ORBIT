"use client";

/**
 * F1 (tri de la mémoire & contradictions) and F2 (fil des changements, abonnements, webhooks):
 * types, endpoint functions and TanStack Query hooks — see docs/FEATURES.md.
 * Kept separate from the shared types/endpoints/hooks modules (feature ownership).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http, request, type ApiError } from "./client";
import { queryKeys } from "./query-keys";
import type { ISODateString, MemoryItem, Page, Provenance, UUID } from "./types";
import type { MemoryKind } from "@/lib/enums";

/* -------------------------------------------------------------------------- */
/* Types                                                                      */
/* -------------------------------------------------------------------------- */

export type InboxSort = "impact" | "confidence" | "recent";
export type BulkAction = "validate" | "reject" | "merge";

export interface InboxItem extends MemoryItem {
  impact: number;
  would_be_included: number;
  similar: { id: UUID; title: string; score: number } | null;
}

export interface InboxParams {
  kind?: MemoryKind;
  min_confidence?: number;
  sort?: InboxSort;
  page?: number;
  page_size?: number;
}

export interface InboxCount {
  proposals: number;
  conflicts: number;
  total: number;
}

export interface BulkIn {
  action: BulkAction;
  ids: UUID[];
  into_id?: UUID;
  reason?: string;
}

export interface BulkOut {
  processed: number;
  failed: { id: UUID; detail: string }[];
}

export interface ConflictSide extends MemoryItem {
  sources: Provenance[];
}

export type ConflictStatus = "open" | "resolved" | "dismissed";

export interface Conflict {
  id: UUID;
  a: ConflictSide;
  b: ConflictSide;
  detected_at: ISODateString;
  similarity: number;
  detail: string | null;
  suggested_winner_id: UUID;
  rationale: string;
  status: ConflictStatus;
  resolution: {
    status: "resolved" | "dismissed";
    winner_id: UUID | null;
    reason: string | null;
    resolved_by: string;
    resolved_at: ISODateString;
  } | null;
}

export const CHANGE_TYPES = [
  "memory.created",
  "memory.validated",
  "memory.superseded",
  "memory.obsoleted",
  "memory.forgotten",
  "memory.conflict_detected",
  "memory.conflict_resolved",
  "document.ingested",
  "document.new_version",
  "document.forgotten",
  "document.stale",
  "snapshot.created",
  "connector.synced",
] as const;
export type ChangeType = (typeof CHANGE_TYPES)[number];

export const CHANGE_TYPE_LABELS: Record<ChangeType, string> = {
  "memory.created": "Nouvelle décision ou contrainte",
  "memory.validated": "Mémoire validée",
  "memory.superseded": "Mémoire remplacée",
  "memory.obsoleted": "Mémoire obsolète",
  "memory.forgotten": "Mémoire oubliée",
  "memory.conflict_detected": "Contradiction détectée",
  "memory.conflict_resolved": "Contradiction arbitrée",
  "document.ingested": "Document ingéré",
  "document.new_version": "Nouvelle version de document",
  "document.forgotten": "Document oublié",
  "document.stale": "Document périmé",
  "snapshot.created": "Snapshot enregistré",
  "connector.synced": "Connecteur synchronisé",
};

export interface ChangeEvent {
  id: UUID;
  project_id: UUID;
  type: ChangeType | string;
  type_label: string;
  title: string;
  summary: string;
  target_type: string;
  target_id: string | null;
  classification: number;
  actor_label: string;
  created_at: ISODateString;
  data: Record<string, unknown>;
}

export interface ChangesParams {
  since?: string;
  types?: string[];
  page?: number;
  page_size?: number;
}

export interface OutdatedItem {
  item_type: "memory" | "document";
  id: UUID;
  title: string;
  reason: "superseded" | "forgotten" | "obsolete" | "edited" | "new_version" | "stale";
  detail: string;
  replaced_by_id: UUID | null;
  replaced_by_title: string | null;
}

export interface SinceSnapshot {
  snapshot: { id: UUID; name: string; version: number; created_at: ISODateString };
  total: number;
  changes: ChangeEvent[];
  outdated: OutdatedItem[];
  hidden_outdated: number;
  is_up_to_date: boolean;
}

export type DigestPeriod = "day" | "week";
export type DigestFrequency = "off" | "daily" | "weekly";

export interface Digest {
  period: DigestPeriod;
  since: ISODateString;
  until: ISODateString;
  total: number;
  groups: { type: string; label: string; count: number; items: ChangeEvent[] }[];
  text: string;
  email_enabled: boolean;
}

export interface Subscription {
  digest: DigestFrequency;
  types: string[];
  last_digest_at: ISODateString | null;
  email_enabled: boolean;
}

export interface Webhook {
  id: UUID;
  url: string;
  description: string;
  types: string[];
  enabled: boolean;
  secret_hint: string;
  consecutive_failures: number;
  disabled_reason: string | null;
  last_delivery_at: ISODateString | null;
  last_status: string | null;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface WebhookCreated extends Webhook {
  secret: string;
}

export interface WebhookIn {
  url: string;
  types: string[];
  description?: string;
}

export interface WebhookPatch {
  url?: string;
  types?: string[];
  description?: string;
  enabled?: boolean;
}

export interface WebhookDelivery {
  id: UUID;
  webhook_id: UUID;
  change_event_id: UUID | null;
  event_type: string;
  status: "pending" | "succeeded" | "failed" | "skipped";
  attempts: number;
  response_status: number | null;
  error: string | null;
  duration_ms: number | null;
  payload: Record<string, unknown>;
  created_at: ISODateString;
  delivered_at: ISODateString | null;
}

/* -------------------------------------------------------------------------- */
/* Endpoints                                                                  */
/* -------------------------------------------------------------------------- */

type Opts = { signal?: AbortSignal };
const e = encodeURIComponent;
const p = (slug: string) => `/projects/${e(slug)}`;

export const featuresFeedApi = {
  listInbox: (slug: string, params: InboxParams = {}, opts: Opts = {}) =>
    http.get<Page<InboxItem>>(`${p(slug)}/inbox`, {
      query: {
        kind: params.kind,
        min_confidence: params.min_confidence,
        sort: params.sort,
        page: params.page,
        page_size: params.page_size,
      },
      ...opts,
    }),
  inboxCount: (slug: string, opts: Opts = {}) => http.get<InboxCount>(`${p(slug)}/inbox/count`, opts),
  bulk: (slug: string, body: BulkIn) => http.post<BulkOut>(`${p(slug)}/inbox/bulk`, body),
  listConflicts: (slug: string, status: "open" | "resolved", opts: Opts = {}) =>
    http.get<Conflict[]>(`${p(slug)}/conflicts`, { query: { status }, ...opts }),
  resolveConflict: (slug: string, id: UUID, body: { winner_id: UUID; reason?: string }) =>
    http.post<Conflict>(`${p(slug)}/conflicts/${e(id)}/resolve`, body),
  dismissConflict: (slug: string, id: UUID, body: { reason?: string }) =>
    http.post<Conflict>(`${p(slug)}/conflicts/${e(id)}/dismiss`, body),

  listChanges: (slug: string, params: ChangesParams = {}, opts: Opts = {}) =>
    http.get<Page<ChangeEvent>>(`${p(slug)}/changes`, {
      query: {
        since: params.since,
        types: params.types && params.types.length ? params.types.join(",") : undefined,
        page: params.page,
        page_size: params.page_size,
      },
      ...opts,
    }),
  sinceSnapshot: (slug: string, name: string, version: number | "latest", opts: Opts = {}) =>
    http.get<SinceSnapshot>(`${p(slug)}/changes/since-snapshot`, { query: { name, version }, ...opts }),
  digest: (slug: string, period: DigestPeriod, opts: Opts = {}) =>
    http.get<Digest>(`${p(slug)}/changes/digest`, { query: { period }, ...opts }),
  getSubscription: (slug: string, opts: Opts = {}) => http.get<Subscription>(`${p(slug)}/subscriptions/me`, opts),
  putSubscription: (slug: string, body: { digest: DigestFrequency; types: string[] }) =>
    request<Subscription>(`${p(slug)}/subscriptions/me`, { method: "PUT", json: body }),

  listWebhooks: (slug: string, opts: Opts = {}) => http.get<Webhook[]>(`${p(slug)}/webhooks`, opts),
  createWebhook: (slug: string, body: WebhookIn) => http.post<WebhookCreated>(`${p(slug)}/webhooks`, body),
  updateWebhook: (slug: string, id: UUID, body: WebhookPatch) =>
    http.patch<Webhook>(`${p(slug)}/webhooks/${e(id)}`, body),
  deleteWebhook: (slug: string, id: UUID) => http.delete(`${p(slug)}/webhooks/${e(id)}`),
  testWebhook: (slug: string, id: UUID) => http.post<WebhookDelivery>(`${p(slug)}/webhooks/${e(id)}/test`),
  listDeliveries: (slug: string, id: UUID, page = 1, opts: Opts = {}) =>
    http.get<Page<WebhookDelivery>>(`${p(slug)}/webhooks/${e(id)}/deliveries`, {
      query: { page, page_size: 20 },
      ...opts,
    }),
};

/* -------------------------------------------------------------------------- */
/* Query keys & hooks                                                         */
/* -------------------------------------------------------------------------- */

const root = (slug: string) => [...queryKeys.project.all(slug), "features-feed"] as const;

export const featuresFeedKeys = {
  inbox: (slug: string) => [...root(slug), "inbox"] as const,
  inboxList: (slug: string, params: InboxParams) => [...root(slug), "inbox", "list", params] as const,
  inboxCount: (slug: string) => [...root(slug), "inbox", "count"] as const,
  conflicts: (slug: string, status: string) => [...root(slug), "inbox", "conflicts", status] as const,
  changes: (slug: string) => [...root(slug), "changes"] as const,
  changesList: (slug: string, params: ChangesParams) => [...root(slug), "changes", "list", params] as const,
  sinceSnapshot: (slug: string, name: string, version: number | "latest") =>
    [...root(slug), "changes", "since", name, version] as const,
  digest: (slug: string, period: DigestPeriod) => [...root(slug), "changes", "digest", period] as const,
  subscription: (slug: string) => [...root(slug), "subscription"] as const,
  webhooks: (slug: string) => [...root(slug), "webhooks"] as const,
  deliveries: (slug: string, id: UUID, page: number) => [...root(slug), "webhooks", id, "deliveries", page] as const,
};

export function useInbox(slug: string, params: InboxParams) {
  return useQuery<Page<InboxItem>, ApiError>({
    queryKey: featuresFeedKeys.inboxList(slug, params),
    queryFn: ({ signal }) => featuresFeedApi.listInbox(slug, params, { signal }),
    enabled: Boolean(slug),
    placeholderData: keepPreviousData,
  });
}

/** Navigation badge: proposals + open conflicts (editors only). */
export function useInboxCount(slug: string | undefined, enabled = true) {
  return useQuery<InboxCount, ApiError>({
    queryKey: featuresFeedKeys.inboxCount(slug ?? ""),
    queryFn: ({ signal }) => featuresFeedApi.inboxCount(slug as string, { signal }),
    enabled: Boolean(slug) && enabled,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function useConflicts(slug: string, status: "open" | "resolved") {
  return useQuery<Conflict[], ApiError>({
    queryKey: featuresFeedKeys.conflicts(slug, status),
    queryFn: ({ signal }) => featuresFeedApi.listConflicts(slug, status, { signal }),
    enabled: Boolean(slug),
  });
}

function useInvalidateTriage(slug: string) {
  const qc = useQueryClient();
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: featuresFeedKeys.inbox(slug) }),
      qc.invalidateQueries({ queryKey: featuresFeedKeys.changes(slug) }),
      qc.invalidateQueries({ queryKey: queryKeys.project.memory.all(slug) }),
      qc.invalidateQueries({ queryKey: queryKeys.project.overview(slug) }),
    ]);
}

export function useBulkInbox(slug: string) {
  const invalidate = useInvalidateTriage(slug);
  return useMutation<BulkOut, ApiError, BulkIn>({
    mutationFn: (body) => featuresFeedApi.bulk(slug, body),
    onSuccess: () => invalidate(),
  });
}

export function useResolveConflict(slug: string) {
  const invalidate = useInvalidateTriage(slug);
  return useMutation<Conflict, ApiError, { id: UUID; winner_id: UUID; reason?: string }>({
    mutationFn: ({ id, ...body }) => featuresFeedApi.resolveConflict(slug, id, body),
    onSuccess: () => invalidate(),
  });
}

export function useDismissConflict(slug: string) {
  const invalidate = useInvalidateTriage(slug);
  return useMutation<Conflict, ApiError, { id: UUID; reason?: string }>({
    mutationFn: ({ id, ...body }) => featuresFeedApi.dismissConflict(slug, id, body),
    onSuccess: () => invalidate(),
  });
}

export function useChanges(slug: string, params: ChangesParams, enabled = true) {
  return useQuery<Page<ChangeEvent>, ApiError>({
    queryKey: featuresFeedKeys.changesList(slug, params),
    queryFn: ({ signal }) => featuresFeedApi.listChanges(slug, params, { signal }),
    enabled: Boolean(slug) && enabled,
    placeholderData: keepPreviousData,
  });
}

export function useSinceSnapshot(slug: string, name: string | null, version: number | "latest") {
  return useQuery<SinceSnapshot, ApiError>({
    queryKey: featuresFeedKeys.sinceSnapshot(slug, name ?? "", version),
    queryFn: ({ signal }) => featuresFeedApi.sinceSnapshot(slug, name as string, version, { signal }),
    enabled: Boolean(slug && name),
  });
}

export function useDigest(slug: string, period: DigestPeriod, enabled = true) {
  return useQuery<Digest, ApiError>({
    queryKey: featuresFeedKeys.digest(slug, period),
    queryFn: ({ signal }) => featuresFeedApi.digest(slug, period, { signal }),
    enabled: Boolean(slug) && enabled,
  });
}

export function useSubscription(slug: string) {
  return useQuery<Subscription, ApiError>({
    queryKey: featuresFeedKeys.subscription(slug),
    queryFn: ({ signal }) => featuresFeedApi.getSubscription(slug, { signal }),
    enabled: Boolean(slug),
  });
}

export function useUpdateSubscription(slug: string) {
  const qc = useQueryClient();
  return useMutation<Subscription, ApiError, { digest: DigestFrequency; types: string[] }>({
    mutationFn: (body) => featuresFeedApi.putSubscription(slug, body),
    onSuccess: (data) => {
      qc.setQueryData(featuresFeedKeys.subscription(slug), data);
      return qc.invalidateQueries({ queryKey: [...featuresFeedKeys.changes(slug), "digest"] });
    },
  });
}

export function useWebhooks(slug: string, enabled = true) {
  return useQuery<Webhook[], ApiError>({
    queryKey: featuresFeedKeys.webhooks(slug),
    queryFn: ({ signal }) => featuresFeedApi.listWebhooks(slug, { signal }),
    enabled: Boolean(slug) && enabled,
  });
}

function useInvalidateWebhooks(slug: string) {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: featuresFeedKeys.webhooks(slug) });
}

export function useCreateWebhook(slug: string) {
  const invalidate = useInvalidateWebhooks(slug);
  return useMutation<WebhookCreated, ApiError, WebhookIn>({
    mutationFn: (body) => featuresFeedApi.createWebhook(slug, body),
    onSuccess: () => invalidate(),
    meta: { silentError: true },
  });
}

export function useUpdateWebhook(slug: string) {
  const invalidate = useInvalidateWebhooks(slug);
  return useMutation<Webhook, ApiError, { id: UUID } & WebhookPatch>({
    mutationFn: ({ id, ...body }) => featuresFeedApi.updateWebhook(slug, id, body),
    onSuccess: () => invalidate(),
  });
}

export function useDeleteWebhook(slug: string) {
  const invalidate = useInvalidateWebhooks(slug);
  return useMutation<unknown, ApiError, UUID>({
    mutationFn: (id) => featuresFeedApi.deleteWebhook(slug, id),
    onSuccess: () => invalidate(),
  });
}

export function useTestWebhook(slug: string) {
  const invalidate = useInvalidateWebhooks(slug);
  return useMutation<WebhookDelivery, ApiError, UUID>({
    mutationFn: (id) => featuresFeedApi.testWebhook(slug, id),
    onSuccess: () => invalidate(),
  });
}

export function useWebhookDeliveries(slug: string, id: UUID | null, page = 1) {
  return useQuery<Page<WebhookDelivery>, ApiError>({
    queryKey: featuresFeedKeys.deliveries(slug, id ?? "", page),
    queryFn: ({ signal }) => featuresFeedApi.listDeliveries(slug, id as string, page, { signal }),
    enabled: Boolean(slug && id),
    placeholderData: keepPreviousData,
  });
}
