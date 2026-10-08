"use client";

import * as React from "react";
import { keepPreviousData, useQueries } from "@tanstack/react-query";

import type { ApiError } from "@/lib/api/client";
import { listMemory } from "@/lib/api/endpoints";
import { useMemoryGraph, useMemoryList } from "@/lib/api/hooks";
import { queryKeys } from "@/lib/api/query-keys";
import type { MemoryGraph, MemoryItem, MemoryListParams, Page } from "@/lib/api/types";
import { MEMORY_STATUSES, type MemoryKind, type MemoryScope, type MemoryStatus } from "@/lib/enums";
import { dateInputToIso } from "./memory-dates";

export const MEMORY_PAGE_SIZE = 30;
/** Per-kind fetch size when several kinds are selected (the API filters one kind at a time). */
const MULTI_KIND_PAGE_SIZE = 100;

export interface MemoryFilters {
  scope: MemoryScope | "all";
  status: MemoryStatus | "all";
  kinds: MemoryKind[];
  q: string;
  history: boolean;
  /** §D2 « tel que connu au » (YYYY-MM-DD). */
  asOf?: string;
}

function baseParams(filters: Omit<MemoryFilters, "status" | "kinds">): MemoryListParams {
  const params: MemoryListParams = {};
  if (filters.scope !== "all") params.scope = filters.scope;
  const q = filters.q.trim();
  if (q) params.q = q;
  if (filters.history) params.include_history = true;
  if (filters.asOf) params.as_of = dateInputToIso(filters.asOf, "end");
  return params;
}

export interface MemoryResults {
  items: MemoryItem[];
  total: number;
  /** Server-side pagination is available (0 or 1 kind selected). */
  paginated: boolean;
  /** Multi-kind mode hit the per-kind fetch limit. */
  truncated: boolean;
  isPending: boolean;
  isFetching: boolean;
  isPlaceholderData: boolean;
  error: ApiError | null;
  refetch: () => void;
}

function sortByRecency(a: MemoryItem, b: MemoryItem): number {
  return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
}

/**
 * Memory items for the current filters. One kind (or none) → server-side filter + pagination;
 * several kinds → one request per kind (merged, most recent first).
 */
export function useMemoryResults(slug: string, filters: MemoryFilters, page: number): MemoryResults {
  const multi = filters.kinds.length > 1;
  const common = baseParams(filters);
  if (filters.status !== "all") common.status = filters.status;

  const single = useMemoryList(
    slug,
    { ...common, kind: filters.kinds[0], page, page_size: MEMORY_PAGE_SIZE },
    { enabled: Boolean(slug) && !multi },
  );

  const multiQueries = useQueries({
    queries: (multi ? filters.kinds : []).map((kind) => {
      const params: MemoryListParams = { ...common, kind, page: 1, page_size: MULTI_KIND_PAGE_SIZE };
      return {
        queryKey: queryKeys.project.memory.list(slug, params),
        queryFn: ({ signal }: { signal: AbortSignal }) => listMemory(slug, params, { signal }),
        enabled: Boolean(slug),
        placeholderData: keepPreviousData,
      };
    }),
  });

  const multiData = multiQueries.map((q) => q.data as Page<MemoryItem> | undefined);
  const multiKey = multiQueries.map((q) => q.dataUpdatedAt).join(",");
  const merged = React.useMemo(() => {
    if (!multi) return null;
    const seen = new Set<string>();
    const items: MemoryItem[] = [];
    let total = 0;
    let truncated = false;
    for (const pageData of multiData) {
      if (!pageData) continue;
      total += pageData.total;
      if (pageData.total > pageData.items.length) truncated = true;
      for (const item of pageData.items) {
        if (seen.has(item.id)) continue;
        seen.add(item.id);
        items.push(item);
      }
    }
    items.sort(sortByRecency);
    return { items, total, truncated };
    // multiKey tracks the query data identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [multi, multiKey]);

  if (multi) {
    const firstError = multiQueries.find((q) => q.error)?.error ?? null;
    return {
      items: merged?.items ?? [],
      total: merged?.total ?? 0,
      paginated: false,
      truncated: merged?.truncated ?? false,
      isPending: multiQueries.some((q) => q.isPending),
      isFetching: multiQueries.some((q) => q.isFetching),
      isPlaceholderData: multiQueries.some((q) => q.isPlaceholderData),
      error: (firstError as ApiError | null) ?? null,
      refetch: () => multiQueries.forEach((q) => void q.refetch()),
    };
  }

  return {
    items: single.data?.items ?? [],
    total: single.data?.total ?? 0,
    paginated: true,
    truncated: false,
    isPending: single.isPending,
    isFetching: single.isFetching,
    isPlaceholderData: single.isPlaceholderData,
    error: single.error ?? null,
    refetch: () => void single.refetch(),
  };
}

export interface StatusCounts {
  byStatus: Partial<Record<MemoryStatus, number>>;
  total: number | undefined;
  isPending: boolean;
}

/** Filter-aware counts per status (cheap `page_size=1` requests, summed over the selected kinds). */
export function useMemoryStatusCounts(slug: string, filters: Omit<MemoryFilters, "status">): StatusCounts {
  const common = baseParams(filters);
  const kinds: ReadonlyArray<MemoryKind | undefined> = filters.kinds.length > 0 ? filters.kinds : [undefined];
  const combos = MEMORY_STATUSES.flatMap((status) => kinds.map((kind) => ({ status, kind })));

  const results = useQueries({
    queries: combos.map(({ status, kind }) => {
      const params: MemoryListParams = { ...common, status, page: 1, page_size: 1 };
      if (kind) params.kind = kind;
      return {
        queryKey: queryKeys.project.memory.list(slug, params),
        queryFn: ({ signal }: { signal: AbortSignal }) => listMemory(slug, params, { signal }),
        enabled: Boolean(slug),
        staleTime: 30_000,
        placeholderData: keepPreviousData,
        select: (data: Page<MemoryItem>) => data.total,
      };
    }),
  });

  const key = results.map((r) => `${r.data ?? ""}`).join(",");
  return React.useMemo(() => {
    const byStatus: Partial<Record<MemoryStatus, number>> = {};
    let total = 0;
    let complete = true;
    combos.forEach(({ status }, index) => {
      const value = results[index]?.data;
      if (typeof value !== "number") {
        complete = false;
        return;
      }
      byStatus[status] = (byStatus[status] ?? 0) + value;
      total += value;
    });
    return { byStatus, total: complete ? total : undefined, isPending: !complete };
    // `key` summarises the query results; combos derive from the same filters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}

export interface GraphInsights {
  graph: MemoryGraph | undefined;
  /** Ids involved in a `contradicts` edge. */
  conflictIds: ReadonlySet<string>;
  /** Node id → label (resolves "remplacé par …" titles without extra requests). */
  labels: ReadonlyMap<string, string>;
}

/** Derived lookups from the (cached) relation graph, used by list cards. Failures are non-blocking. */
export function useGraphInsights(slug: string, limit = 150): GraphInsights {
  const { data } = useMemoryGraph(slug, limit, { staleTime: 60_000 });
  return React.useMemo(() => {
    const conflictIds = new Set<string>();
    const labels = new Map<string, string>();
    for (const node of data?.nodes ?? []) labels.set(node.id, node.label);
    for (const edge of data?.edges ?? []) {
      if (edge.rel_type === "contradicts") {
        conflictIds.add(edge.source);
        conflictIds.add(edge.target);
      }
    }
    return { graph: data, conflictIds, labels };
  }, [data]);
}
