/**
 * Pure helpers for the observability screen: daily series densification, categorical slots for
 * inclusion types, reason/stage rows and status distributions. No React here.
 */
import type { MetricsSeriesPoint } from "@/lib/api/types";
import {
  CANDIDATE_TYPE_META,
  CONTEXT_STAGES,
  CONTEXT_STAGE_META,
  MEMORY_KIND_META,
  REASON_CODE_META,
  REASON_CODE_ORDER,
  getMeta,
  type EnumMeta,
  type ReasonCode,
  type Tone,
} from "@/lib/enums";

export const PERIOD_OPTIONS = [7, 14, 30] as const;
export type PeriodDays = (typeof PERIOD_OPTIONS)[number];
export const DEFAULT_PERIOD: PeriodDays = 14;

export function isPeriod(value: unknown): value is PeriodDays {
  return typeof value === "number" && (PERIOD_OPTIONS as readonly number[]).includes(value);
}

/* -------------------------------------------------------------------------- */
/* Daily series                                                               */
/* -------------------------------------------------------------------------- */

export interface DailyPoint {
  /** YYYY-MM-DD */
  date: string;
  requests: number;
  p50: number | null;
  p95: number | null;
  tokens: number;
  cost: number;
}

function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function num(v: unknown): number {
  const n = typeof v === "string" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) ? n : 0;
}

/**
 * One point per day over the last `days` days (UTC, today included); missing days are zero-filled and
 * latency is `null` on days without requests so lines break instead of dropping to 0.
 */
export function densifySeries(series: readonly MetricsSeriesPoint[], days: number, now: Date = new Date()): DailyPoint[] {
  const byDate = new Map<string, MetricsSeriesPoint>();
  for (const p of series) byDate.set(String(p.date).slice(0, 10), p);

  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const lastSeries = [...byDate.keys()].sort().pop();
  if (lastSeries && lastSeries > isoDay(end)) end.setTime(Date.parse(`${lastSeries}T00:00:00Z`));

  const out: DailyPoint[] = [];
  for (let i = Math.max(1, days) - 1; i >= 0; i--) {
    const d = new Date(end.getTime() - i * 86_400_000);
    const key = isoDay(d);
    const p = byDate.get(key);
    const requests = num(p?.requests);
    out.push({
      date: key,
      requests,
      p50: requests > 0 && p?.p50_latency_ms != null ? num(p.p50_latency_ms) : null,
      p95: requests > 0 && p?.p95_latency_ms != null ? num(p.p95_latency_ms) : null,
      tokens: num(p?.tokens),
      cost: num(p?.cost_estimate),
    });
  }
  return out;
}

/* -------------------------------------------------------------------------- */
/* Inclusions by type (categorical slots, fixed order)                        */
/* -------------------------------------------------------------------------- */

/**
 * Fixed categorical slot per inclusion type — colour follows the entity, never its rank.
 * Slots map to `--chart-1..6` in their validated adjacency order; everything else folds into "Autres".
 */
const INCLUSION_SLOTS: ReadonlyArray<{ key: string; slot: number }> = [
  { key: "memory:decision", slot: 0 },
  { key: "memory:constraint", slot: 1 },
  { key: "chunk", slot: 2 },
  { key: "memory:fact", slot: 3 },
  { key: "memory:requirement", slot: 4 },
  { key: "memory:risk", slot: 5 },
];

export const OTHER_KEY = "other";

export function inclusionTypeLabel(key: string): string {
  if (key === OTHER_KEY) return "Autres";
  if (key === "chunk") return "Extraits de sources";
  if (key.startsWith("memory:")) {
    const kind = key.slice("memory:".length);
    const meta = getMeta(MEMORY_KIND_META, kind);
    return kind ? `Mémoire · ${meta.label}` : CANDIDATE_TYPE_META.memory.label;
  }
  if (key === "memory") return CANDIDATE_TYPE_META.memory.label;
  if (key === "session" || key.startsWith("session:")) return "Session en cours";
  return key;
}

export interface InclusionSlice {
  key: string;
  label: string;
  value: number;
  ratio: number;
  /** Index in CHART_COLORS, or -1 for "Autres" (neutral). */
  slot: number;
  /** Keys folded into this slice (for "Autres"). */
  members: string[];
}

export function buildInclusionSlices(inclusions: Record<string, number> | null | undefined): InclusionSlice[] {
  const entries = Object.entries(inclusions ?? {}).filter(([, v]) => typeof v === "number" && v > 0);
  const total = entries.reduce((acc, [, v]) => acc + v, 0);
  if (total === 0) return [];
  const slices: InclusionSlice[] = [];
  const other: InclusionSlice = { key: OTHER_KEY, label: "Autres", value: 0, ratio: 0, slot: -1, members: [] };
  for (const [key, value] of entries) {
    const slot = INCLUSION_SLOTS.find((s) => s.key === key)?.slot;
    if (slot === undefined) {
      other.value += value;
      other.members.push(key);
    } else {
      slices.push({ key, label: inclusionTypeLabel(key), value, ratio: value / total, slot, members: [key] });
    }
  }
  slices.sort((a, b) => a.slot - b.slot);
  if (other.value > 0) {
    other.ratio = other.value / total;
    other.label = other.members.length === 1 ? inclusionTypeLabel(other.members[0] ?? OTHER_KEY) : "Autres";
    slices.push(other);
  }
  return slices;
}

/* -------------------------------------------------------------------------- */
/* Exclusions by reason                                                       */
/* -------------------------------------------------------------------------- */

export interface ReasonRow {
  code: string;
  label: string;
  short: string;
  count: number;
  tone: Tone;
}

const REASON_INDEX = new Map<string, number>(REASON_CODE_ORDER.map((c, i) => [c, i]));

export function buildReasonRows(exclusions: Partial<Record<ReasonCode, number>> | null | undefined): ReasonRow[] {
  return Object.entries(exclusions ?? {})
    .filter(([code, v]) => typeof v === "number" && v > 0 && !code.startsWith("INCLUDED_"))
    .map(([code, v]) => {
      const meta = REASON_CODE_META[code as ReasonCode];
      return {
        code,
        label: meta?.label ?? code,
        short: meta?.short ?? code,
        count: v as number,
        tone: meta?.tone ?? "neutral",
      };
    })
    .sort((a, b) => b.count - a.count || (REASON_INDEX.get(a.code) ?? 99) - (REASON_INDEX.get(b.code) ?? 99));
}

/* -------------------------------------------------------------------------- */
/* Stage latency                                                              */
/* -------------------------------------------------------------------------- */

export interface StageRow {
  key: string;
  label: string;
  description: string;
  ms: number;
}

const EXTRA_STAGE_LABELS: Record<string, string> = { persist: "Persistance" };

/** Average latency per stage, in execution order; unknown stages appended; `total` excluded. */
export function buildStageRows(stageAvg: Record<string, number> | null | undefined): StageRow[] {
  const source = stageAvg ?? {};
  const rows: StageRow[] = CONTEXT_STAGES.filter((s) => typeof source[s] === "number").map((s) => ({
    key: s,
    label: CONTEXT_STAGE_META[s].label,
    description: CONTEXT_STAGE_META[s].description ?? "",
    ms: num(source[s]),
  }));
  for (const [key, value] of Object.entries(source)) {
    if (key === "total" || (CONTEXT_STAGES as readonly string[]).includes(key)) continue;
    rows.push({ key, label: EXTRA_STAGE_LABELS[key] ?? key, description: "", ms: num(value) });
  }
  return rows;
}

/* -------------------------------------------------------------------------- */
/* Status distributions                                                       */
/* -------------------------------------------------------------------------- */

export interface StatusSegment {
  key: string;
  label: string;
  tone: Tone;
  count: number;
  ratio: number;
}

/** Status counts in the canonical order of `values`, with labels and tones from `meta`. */
export function buildStatusSegments<K extends string>(
  counts: Partial<Record<K, number>> | null | undefined,
  values: readonly K[],
  meta: Record<K, EnumMeta>,
): { total: number; segments: StatusSegment[] } {
  const source = (counts ?? {}) as Partial<Record<string, number>>;
  const keys = [...values, ...Object.keys(source).filter((k) => !(values as readonly string[]).includes(k))];
  const total = keys.reduce((acc, k) => acc + num(source[k]), 0);
  const segments = keys
    .map((k) => {
      const m = getMeta(meta as Record<string, EnumMeta>, k);
      const count = num(source[k]);
      return { key: k, label: m.label, tone: m.tone, count, ratio: total > 0 ? count / total : 0 };
    })
    .filter((s) => s.count > 0);
  return { total, segments };
}
