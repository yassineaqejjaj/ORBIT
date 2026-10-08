"use client";

import * as React from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import {
  isEnumValue,
  MEMORY_KINDS,
  MEMORY_SCOPES,
  MEMORY_STATUSES,
  type MemoryKind,
  type MemoryScope,
  type MemoryStatus,
} from "@/lib/enums";

export type MemoryView = "list" | "graph";

/** Explorer state mirrored in the URL (`?item=&scope=&status=&kind=&q=&history=1&view=graph&page=`). */
export interface MemoryUrlState {
  item: string | null;
  scope: MemoryScope | "all";
  status: MemoryStatus | "all";
  kinds: MemoryKind[];
  q: string;
  history: boolean;
  /** §D2 « tel que connu au » (YYYY-MM-DD, empty = now). */
  asOf: string;
  view: MemoryView;
  page: number;
}

export type MemoryUrlPatch = Partial<MemoryUrlState>;

function parseState(params: URLSearchParams): MemoryUrlState {
  const scope = params.get("scope");
  const status = params.get("status");
  const kinds = (params.get("kind") ?? "")
    .split(",")
    .map((k) => k.trim())
    .filter((k): k is MemoryKind => isEnumValue(MEMORY_KINDS, k));
  const page = Number.parseInt(params.get("page") ?? "1", 10);
  return {
    item: params.get("item") || null,
    scope: isEnumValue(MEMORY_SCOPES, scope) ? scope : "all",
    status: isEnumValue(MEMORY_STATUSES, status) ? status : "all",
    kinds: Array.from(new Set(kinds)),
    q: params.get("q") ?? "",
    history: params.get("history") === "1",
    asOf: /^\d{4}-\d{2}-\d{2}$/.test(params.get("as_of") ?? "") ? (params.get("as_of") as string) : "",
    view: params.get("view") === "graph" ? "graph" : "list",
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

function serialize(state: MemoryUrlState): string {
  const params = new URLSearchParams();
  if (state.item) params.set("item", state.item);
  if (state.scope !== "all") params.set("scope", state.scope);
  if (state.status !== "all") params.set("status", state.status);
  if (state.kinds.length > 0) params.set("kind", state.kinds.join(","));
  if (state.q.trim()) params.set("q", state.q.trim());
  if (state.history) params.set("history", "1");
  if (state.asOf) params.set("as_of", state.asOf);
  if (state.view === "graph") params.set("view", "graph");
  if (state.page > 1) params.set("page", String(state.page));
  return params.toString();
}

const FILTER_KEYS: ReadonlyArray<keyof MemoryUrlState> = ["scope", "status", "kinds", "q", "history", "asOf"];

/**
 * Reads/writes the explorer state from/to the query string (deep-linkable: the overview links to `?item=`).
 * Changing a filter resets the page to 1. Uses `router.replace` (no history spam, no scroll jump).
 */
export function useMemoryUrlState(): [MemoryUrlState, (patch: MemoryUrlPatch) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const raw = searchParams.toString();
  const state = React.useMemo(() => parseState(new URLSearchParams(raw)), [raw]);

  const stateRef = React.useRef(state);
  React.useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const update = React.useCallback(
    (patch: MemoryUrlPatch) => {
      const prev = stateRef.current;
      const next: MemoryUrlState = { ...prev, ...patch };
      if (patch.page === undefined && FILTER_KEYS.some((k) => k in patch)) next.page = 1;
      stateRef.current = next;
      const qs = serialize(next);
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router],
  );

  return [state, update];
}
