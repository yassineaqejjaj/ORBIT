/**
 * Évaluation & apprentissage (docs/AI_CONTEXT_ENGINEERING.md §E1–E3): golden sets, runs and comparison,
 * bounded ranking weights learned from feedback, LLM-judge verdicts. Types, endpoints and hooks.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type ApiError, http } from "./client";
import { queryKeys } from "./query-keys";
import type { ISODateString, UUID } from "./types";

export interface EvalExpected {
  type: "memory" | "document";
  id: UUID;
  title?: string;
}

export interface EvalCase {
  id: UUID;
  question: string;
  expected: EvalExpected[];
  origin: "manual" | "generated" | string;
  created_at: ISODateString;
}

export interface EvalMetrics {
  recall?: number | null;
  ndcg?: number | null;
  sufficiency?: number | null;
  citation_faithfulness?: number | null;
  cases?: number;
}

export interface EvalRunSummary {
  id: UUID;
  set_id: UUID;
  status: "queued" | "running" | "succeeded" | "failed" | string;
  trigger: string;
  k: number;
  min_recall: number | null;
  metrics: EvalMetrics;
  passed: boolean | null;
  error?: string | null;
  created_at: ISODateString;
  finished_at?: ISODateString | null;
}

export interface EvalRunCase {
  case_id: UUID;
  question: string;
  expected: number;
  found: string[];
  recall: number;
  ndcg: number;
  citation_faithfulness: number;
  sufficiency: number | null;
  request_id: UUID;
}

export interface EvalRun extends EvalRunSummary {
  cases: EvalRunCase[];
  config: Record<string, unknown>;
}

export interface EvalSet {
  id: UUID;
  name: string;
  description: string;
  cases_count: number;
  last_run: EvalRunSummary | null;
  created_at: ISODateString;
}

export interface EvalSetDetail extends EvalSet {
  cases: EvalCase[];
}

export interface EvalCompare {
  base: EvalRunSummary;
  target: EvalRunSummary;
  delta: Record<string, number | null>;
  cases: { case_id: UUID; question: string; base_recall: number | null; target_recall: number | null }[];
}

export type WeightKey = "rrf" | "dense" | "freshness" | "type" | "terms";

export interface WeightChange {
  id: UUID;
  reason: "learn" | "revert" | "reset";
  before: Record<WeightKey, number>;
  after: Record<WeightKey, number>;
  signals: Record<string, number>;
  reverts_id: UUID | null;
  reverted_at: ISODateString | null;
  actor: string;
  created_at: ISODateString;
}

export interface RankingWeights {
  enabled: boolean;
  weights: Record<WeightKey, number>;
  defaults: Record<WeightKey, number>;
  bounds: Record<WeightKey, [number, number]>;
  max_delta: number;
  min_signals: number;
  history: WeightChange[];
  outcome: "adjusted" | "unchanged" | "reverted" | "reset" | null;
}

export interface Judgement {
  request_id: UUID;
  task: string;
  method: "llm" | "skipped_guardrail" | "heuristic" | string;
  model: string | null;
  score: number | null;
  verdict: string | null;
  explanation: string;
  served_at: ISODateString;
  judged_at: ISODateString;
}

export interface JudgementsView {
  sample_rate: number;
  threshold: number;
  window_days: number;
  window_count: number;
  window_average: number | null;
  alerts: string[];
  items: Judgement[];
}

const p = (slug: string) => `/projects/${encodeURIComponent(slug)}/evaluation`;
type Opts = { signal?: AbortSignal };

export const evalApi = {
  sets: (slug: string, opts: Opts = {}) => http.get<EvalSet[]>(`${p(slug)}/sets`, opts),
  set: (slug: string, id: UUID, opts: Opts = {}) => http.get<EvalSetDetail>(`${p(slug)}/sets/${id}`, opts),
  createSet: (slug: string, body: { name: string; description?: string }) =>
    http.post<EvalSetDetail>(`${p(slug)}/sets`, body),
  deleteSet: (slug: string, id: UUID) => http.delete(`${p(slug)}/sets/${id}`),
  addCase: (slug: string, id: UUID, body: { question: string; expected: EvalExpected[] }) =>
    http.post<EvalCase>(`${p(slug)}/sets/${id}/cases`, body),
  deleteCase: (slug: string, id: UUID, caseId: UUID) => http.delete(`${p(slug)}/sets/${id}/cases/${caseId}`),
  generate: (slug: string, id: UUID, limit = 10) =>
    http.post<EvalCase[]>(`${p(slug)}/sets/${id}/generate`, { limit }),
  startRun: (slug: string, id: UUID, body: { k?: number; min_recall?: number } = {}) =>
    http.post<EvalRunSummary>(`${p(slug)}/sets/${id}/runs`, body),
  runs: (slug: string, opts: Opts = {}) => http.get<EvalRunSummary[]>(`${p(slug)}/runs`, opts),
  run: (slug: string, id: UUID, opts: Opts = {}) => http.get<EvalRun>(`${p(slug)}/runs/${id}`, opts),
  compare: (slug: string, base: UUID, target: UUID, opts: Opts = {}) =>
    http.get<EvalCompare>(`${p(slug)}/compare`, { ...opts, query: { base, target } }),
  weights: (slug: string, opts: Opts = {}) => http.get<RankingWeights>(`${p(slug)}/ranking-weights`, opts),
  learn: (slug: string) => http.post<RankingWeights>(`${p(slug)}/ranking-weights/learn`),
  revert: (slug: string, id: UUID) => http.post<RankingWeights>(`${p(slug)}/ranking-weights/${id}/revert`),
  reset: (slug: string) => http.post<RankingWeights>(`${p(slug)}/ranking-weights/reset`),
  judgements: (slug: string, opts: Opts = {}) => http.get<JudgementsView>(`${p(slug)}/judgements`, opts),
  exportUrl: (slug: string) => `/api/v1${p(slug)}/judgements/export`,
};

export const evalKeys = {
  all: (slug: string) => [...queryKeys.project.all(slug), "evaluation"] as const,
  sets: (slug: string) => [...evalKeys.all(slug), "sets"] as const,
  set: (slug: string, id: string) => [...evalKeys.all(slug), "set", id] as const,
  runs: (slug: string) => [...evalKeys.all(slug), "runs"] as const,
  run: (slug: string, id: string) => [...evalKeys.all(slug), "run", id] as const,
  compare: (slug: string, a: string, b: string) => [...evalKeys.all(slug), "compare", a, b] as const,
  weights: (slug: string) => [...evalKeys.all(slug), "weights"] as const,
  judgements: (slug: string) => [...evalKeys.all(slug), "judgements"] as const,
};

const isPending = (runs: EvalRunSummary[] | undefined) =>
  (runs ?? []).some((r) => r.status === "queued" || r.status === "running");

export function useEvalSets(slug: string) {
  return useQuery<EvalSet[], ApiError>({
    queryKey: evalKeys.sets(slug),
    queryFn: ({ signal }) => evalApi.sets(slug, { signal }),
    enabled: Boolean(slug),
  });
}

export function useEvalSet(slug: string, id: UUID | null) {
  return useQuery<EvalSetDetail, ApiError>({
    queryKey: evalKeys.set(slug, id ?? ""),
    queryFn: ({ signal }) => evalApi.set(slug, id as string, { signal }),
    enabled: Boolean(slug && id),
  });
}

export function useEvalRuns(slug: string) {
  return useQuery<EvalRunSummary[], ApiError>({
    queryKey: evalKeys.runs(slug),
    queryFn: ({ signal }) => evalApi.runs(slug, { signal }),
    enabled: Boolean(slug),
    refetchInterval: (query) => (isPending(query.state.data) ? 3000 : false),
  });
}

export function useEvalRun(slug: string, id: UUID | null) {
  return useQuery<EvalRun, ApiError>({
    queryKey: evalKeys.run(slug, id ?? ""),
    queryFn: ({ signal }) => evalApi.run(slug, id as string, { signal }),
    enabled: Boolean(slug && id),
  });
}

export function useEvalCompare(slug: string, base: UUID | null, target: UUID | null) {
  return useQuery<EvalCompare, ApiError>({
    queryKey: evalKeys.compare(slug, base ?? "", target ?? ""),
    queryFn: ({ signal }) => evalApi.compare(slug, base as string, target as string, { signal }),
    enabled: Boolean(slug && base && target && base !== target),
  });
}

export function useEvalMutation<TVars, TOut = unknown>(slug: string, fn: (vars: TVars) => Promise<TOut>) {
  const qc = useQueryClient();
  return useMutation<TOut, ApiError, TVars>({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: evalKeys.all(slug) }),
  });
}

export function useRankingWeights(slug: string) {
  return useQuery<RankingWeights, ApiError>({
    queryKey: evalKeys.weights(slug),
    queryFn: ({ signal }) => evalApi.weights(slug, { signal }),
    enabled: Boolean(slug),
  });
}

export function useJudgements(slug: string) {
  return useQuery<JudgementsView, ApiError>({
    queryKey: evalKeys.judgements(slug),
    queryFn: ({ signal }) => evalApi.judgements(slug, { signal }),
    enabled: Boolean(slug),
  });
}
