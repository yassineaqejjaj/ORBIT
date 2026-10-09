"use client";

/**
 * Live project events (SSE `GET /api/v1/projects/{slug}/events/stream`): ids only, never content.
 * `LiveEventsProvider` is mounted once in the project layout; consumers read the connection state and
 * use `useLivePollInterval` as a fallback (poll every 10 s, tab visible only) when the stream is not live.
 */
import * as React from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";

import { featuresFeedKeys } from "@/lib/api/features-feed";
import { queryKeys } from "@/lib/api/query-keys";

export type LiveState = "connecting" | "connected" | "reconnecting" | "polling";

export const LIVE_KINDS = ["context.served", "ingestion.updated", "memory.changed", "snapshot.created"] as const;
export type LiveKind = (typeof LIVE_KINDS)[number];

const POLL_MS = 10_000;
const DEBOUNCE_MS = 400;
const BACKOFF_MS = [1_000, 2_000, 4_000, 8_000, 15_000, 30_000];
/** Consecutive failures before the UI declares « polling » (it keeps retrying in the background). */
const POLLING_AFTER = 3;

const LiveContext = React.createContext<LiveState>("polling");

export function useLiveState(): LiveState {
  return React.useContext(LiveContext);
}

/** `refetchInterval` fallback: 10 s while the stream is down, only when the tab is visible. */
export function useLivePollInterval(): () => number | false {
  const state = useLiveState();
  return React.useCallback(() => {
    if (state === "connected" || state === "connecting") return false;
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return false;
    return POLL_MS;
  }, [state]);
}

/** Queries refreshed per event kind (prefix keys). */
function invalidate(qc: QueryClient, slug: string, kinds: Set<string>) {
  const all = queryKeys.project.all(slug);
  const keys: (readonly unknown[])[] = [];
  if (kinds.has("context.served")) {
    keys.push(
      queryKeys.project.context.all(slug),
      queryKeys.project.overview(slug),
      [...all, "metrics"],
      featuresFeedKeys.changes(slug),
    );
  }
  if (kinds.has("ingestion.updated")) {
    keys.push(
      queryKeys.project.jobs.all(slug),
      queryKeys.project.documents.all(slug),
      queryKeys.project.overview(slug),
      queryKeys.project.sources(slug),
      featuresFeedKeys.changes(slug),
    );
  }
  if (kinds.has("memory.changed")) {
    keys.push(
      queryKeys.project.memory.all(slug),
      queryKeys.project.overview(slug),
      featuresFeedKeys.inbox(slug),
      featuresFeedKeys.changes(slug),
    );
  }
  if (kinds.has("snapshot.created")) {
    keys.push(queryKeys.project.snapshots.all(slug), featuresFeedKeys.changes(slug));
  }
  for (const queryKey of keys) void qc.invalidateQueries({ queryKey });
}

export function LiveEventsProvider({ slug, children }: { slug: string; children: React.ReactNode }) {
  const qc = useQueryClient();
  const [state, setState] = React.useState<LiveState>("connecting");

  React.useEffect(() => {
    if (!slug) return;
    if (typeof window === "undefined" || typeof window.EventSource === "undefined") {
      setState("polling");
      return;
    }
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let flush: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    let lastId = "";
    let closed = false;
    const pending = new Set<string>();

    const schedule = (kind: string) => {
      pending.add(kind);
      if (flush) return;
      flush = setTimeout(() => {
        flush = undefined;
        const kinds = new Set(pending);
        pending.clear();
        invalidate(qc, slug, kinds);
      }, DEBOUNCE_MS);
    };

    const close = () => {
      source?.close();
      source = null;
    };

    const reconnect = (delay?: number) => {
      close();
      if (closed) return;
      failures += 1;
      setState(failures >= POLLING_AFTER ? "polling" : "reconnecting");
      const wait = delay ?? BACKOFF_MS[Math.min(failures - 1, BACKOFF_MS.length - 1)]!;
      clearTimeout(retry);
      retry = setTimeout(open, wait);
    };

    function open() {
      if (closed || document.visibilityState === "hidden") return;
      const url = `/api/v1/projects/${encodeURIComponent(slug)}/events/stream${lastId ? `?last_event_id=${lastId}` : ""}`;
      const es = new EventSource(url, { withCredentials: true });
      source = es;
      es.onopen = () => {
        const recovered = failures > 0;
        failures = 0;
        setState("connected");
        // events may have been missed while disconnected
        if (recovered) invalidate(qc, slug, new Set(LIVE_KINDS));
      };
      es.onerror = () => {
        if (es.readyState === EventSource.CLOSED || source === es) reconnect();
      };
      for (const kind of LIVE_KINDS) {
        es.addEventListener(kind, (ev) => {
          const id = (ev as MessageEvent).lastEventId;
          if (id) lastId = id;
          schedule(kind);
        });
      }
      es.addEventListener("degraded", () => reconnect(60_000));
      es.addEventListener("reconnect", () => {
        close();
        failures = 0;
        open();
      });
    }

    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        close(); // paused while the tab is hidden: no connection held for nothing
        clearTimeout(retry);
      } else if (!source) {
        failures = 0;
        invalidate(qc, slug, new Set(LIVE_KINDS));
        open();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    open();
    return () => {
      closed = true;
      document.removeEventListener("visibilitychange", onVisibility);
      clearTimeout(retry);
      clearTimeout(flush);
      close();
    };
  }, [qc, slug]);

  return <LiveContext.Provider value={state}>{children}</LiveContext.Provider>;
}

/**
 * Ids that appeared after the first non-empty load of a list: highlighted for a few seconds
 * (the baseline is the first data seen, so a page change does not flash everything).
 */
export function useFreshIds(ids: readonly string[], resetKey: string = "", ttlMs = 4_000): ReadonlySet<string> {
  const seen = React.useRef<Set<string> | null>(null);
  const key = React.useRef(resetKey);
  const [fresh, setFresh] = React.useState<ReadonlySet<string>>(new Set());
  const joined = ids.join("|");

  React.useEffect(() => {
    if (key.current !== resetKey) {
      key.current = resetKey;
      seen.current = null;
    }
    if (ids.length === 0) return;
    if (seen.current === null) {
      seen.current = new Set(ids);
      return;
    }
    const added = ids.filter((id) => !seen.current!.has(id));
    ids.forEach((id) => seen.current!.add(id));
    if (added.length === 0) return;
    setFresh((prev) => new Set([...prev, ...added]));
    const timer = setTimeout(() => setFresh((prev) => new Set([...prev].filter((id) => !added.includes(id)))), ttlMs);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [joined, resetKey]);

  return fresh;
}
