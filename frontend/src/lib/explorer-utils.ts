/**
 * Pure helpers for the context explorer (form state, request building, citations, stage timings).
 * No React here: everything is unit-testable and shared by `src/components/explorer/**`.
 */
import type {
  ContextItem,
  ContextRequestIn,
  ContextTimings,
  ExcludedItem,
  Project,
  Scores,
} from "@/lib/api/types";
import {
  CONTEXT_STAGES,
  CONTEXT_STAGE_META,
  INTENTS,
  MEMORY_SCOPES,
  REASON_CODE_ORDER,
  SOURCE_KINDS,
  isEnumValue,
  toClassification,
  type Classification,
  type ContextStage,
  type Intent,
  type MemoryScope,
  type ReasonCode,
  type SourceKind,
} from "@/lib/enums";

/* -------------------------------------------------------------------------- */
/* Constants                                                                  */
/* -------------------------------------------------------------------------- */

/** Task used in the investor demo (docs/DEMO.md §6). */
export const DEMO_TASK = "Rédiger la spécification fonctionnelle du module de réservation pour le pilote de Lyon";

export const TASK_MAX_LENGTH = 8000;
export const BUDGET_MIN = 500;
/** Upper bound of the slider (the numeric input accepts up to the API maximum). */
export const BUDGET_SLIDER_MAX = 16000;
export const BUDGET_MAX = 32000;
export const BUDGET_STEP = 100;
export const FRESHNESS_MAX_DAYS = 36500;

/** Same rule as the backend `SaveSnapshotRef.name`. */
export const SNAPSHOT_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
export const SNAPSHOT_NAME_MAX = 120;

/** Select sentinels (Radix Select forbids empty-string values). */
export const AUTO_INTENT = "auto" as const;
export const HUMAN_AGENT = "human" as const;
export const SELF_PRINCIPAL = "me" as const;
export const NO_CEILING = "none" as const;
export const NO_BASE_SNAPSHOT = "none" as const;
export const LATEST_VERSION = "latest" as const;

/** Prefix of the in-page anchors generated for `[S1]` citations in the assembled Markdown. */
export const CITATION_HREF_PREFIX = "#orbit-cite-";

/* -------------------------------------------------------------------------- */
/* Form state                                                                 */
/* -------------------------------------------------------------------------- */

export type IntentChoice = Intent | typeof AUTO_INTENT;
export type CeilingChoice = `${Classification}` | typeof NO_CEILING;

export interface ExplorerFormState {
  task: string;
  intent: IntentChoice;
  /** Agent id, or `HUMAN_AGENT`. */
  agentId: string;
  /** Member user id, or `SELF_PRINCIPAL`. */
  onBehalfOf: string;
  tokenBudget: number;
  /** Raw input value (days); empty = project policies. */
  freshnessDays: string;
  scopes: MemoryScope[];
  includeSources: boolean;
  sourceKinds: SourceKind[];
  maxClassification: CeilingChoice;
  /** Snapshot name, or `NO_BASE_SNAPSHOT`. */
  baseName: string;
  /** Version number as string, or `LATEST_VERSION`. */
  baseVersion: string;
  saveSnapshot: boolean;
  snapshotName: string;
}

export type ExplorerFormField = "task" | "tokenBudget" | "freshnessDays" | "scopes" | "sourceKinds" | "snapshotName";
export type ExplorerFormErrors = Partial<Record<ExplorerFormField, string>>;

/** Clamp a token budget to the API bounds, rounded to the step. */
export function clampBudget(value: number): number {
  if (!Number.isFinite(value)) return BUDGET_MIN;
  return Math.min(BUDGET_MAX, Math.max(BUDGET_MIN, Math.round(value)));
}

export function defaultBudget(project: Pick<Project, "settings"> | null | undefined): number {
  const raw = project?.settings?.default_token_budget;
  return typeof raw === "number" && raw > 0 ? clampBudget(raw) : 4000;
}

/** Normalizes the `?version=` query value. */
export function parseVersionParam(value: string | null | undefined): string {
  if (!value || value === LATEST_VERSION) return LATEST_VERSION;
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n >= 1 ? String(n) : LATEST_VERSION;
}

export function initialExplorerForm(
  project: Pick<Project, "settings"> | null | undefined,
  base?: { name?: string | null; version?: string | null },
): ExplorerFormState {
  const baseName = base?.name?.trim() ? base.name.trim() : NO_BASE_SNAPSHOT;
  return {
    task: "",
    intent: AUTO_INTENT,
    agentId: HUMAN_AGENT,
    onBehalfOf: SELF_PRINCIPAL,
    tokenBudget: defaultBudget(project),
    freshnessDays: "",
    scopes: [...MEMORY_SCOPES],
    includeSources: true,
    sourceKinds: [...SOURCE_KINDS],
    maxClassification: NO_CEILING,
    baseName,
    baseVersion: baseName === NO_BASE_SNAPSHOT ? LATEST_VERSION : parseVersionParam(base?.version),
    saveSnapshot: false,
    snapshotName: "",
  };
}

export function isIntentChoice(value: string): value is IntentChoice {
  return value === AUTO_INTENT || isEnumValue(INTENTS, value);
}

export function isCeilingChoice(value: string): value is CeilingChoice {
  return value === NO_CEILING || value === "0" || value === "1" || value === "2" || value === "3";
}

function parseFreshness(raw: string): number | null | "invalid" {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  if (!/^\d+$/.test(trimmed)) return "invalid";
  const n = Number.parseInt(trimmed, 10);
  if (n < 1 || n > FRESHNESS_MAX_DAYS) return "invalid";
  return n;
}

/** Client-side validation mirroring the backend `ContextRequestIn` constraints (French messages). */
export function validateExplorerForm(form: ExplorerFormState): ExplorerFormErrors {
  const errors: ExplorerFormErrors = {};
  const task = form.task.trim();
  if (!task) errors.task = "Décrivez la tâche pour laquelle assembler un contexte.";
  else if (task.length > TASK_MAX_LENGTH) errors.task = `La tâche ne doit pas dépasser ${TASK_MAX_LENGTH} caractères.`;

  if (!Number.isFinite(form.tokenBudget) || form.tokenBudget < BUDGET_MIN || form.tokenBudget > BUDGET_MAX) {
    errors.tokenBudget = `Le budget doit être compris entre ${BUDGET_MIN} et ${BUDGET_MAX} tokens.`;
  }

  if (parseFreshness(form.freshnessDays) === "invalid") {
    errors.freshnessDays = `Indiquez un nombre de jours entre 1 et ${FRESHNESS_MAX_DAYS}.`;
  }

  if (form.scopes.length === 0 && !form.includeSources) {
    errors.scopes = "Sélectionnez au moins une portée de mémoire ou incluez les sources.";
  }
  if (form.includeSources && form.sourceKinds.length === 0) {
    errors.sourceKinds = "Sélectionnez au moins un type de source (ou désactivez l'inclusion des sources).";
  }

  if (form.saveSnapshot) {
    const name = form.snapshotName.trim();
    if (!name) errors.snapshotName = "Donnez un nom au snapshot (ex. spec-atlas).";
    else if (name.length > SNAPSHOT_NAME_MAX) errors.snapshotName = `${SNAPSHOT_NAME_MAX} caractères maximum.`;
    else if (!SNAPSHOT_NAME_PATTERN.test(name)) {
      errors.snapshotName = "Lettres, chiffres, « . », « _ » et « - » uniquement, sans espace (ex. spec-atlas).";
    }
  }
  return errors;
}

/** Builds the API payload from a valid form. Defaults are omitted so the backend applies project settings. */
export function buildContextRequest(form: ExplorerFormState, options: { canActOnBehalf: boolean }): ContextRequestIn {
  const body: ContextRequestIn = { task: form.task.trim(), token_budget: clampBudget(form.tokenBudget) };
  if (form.intent !== AUTO_INTENT) body.intent = form.intent;
  if (form.agentId !== HUMAN_AGENT) body.agent_id = form.agentId;
  if (options.canActOnBehalf && form.onBehalfOf !== SELF_PRINCIPAL) body.on_behalf_of = form.onBehalfOf;

  const freshness = parseFreshness(form.freshnessDays);
  if (typeof freshness === "number") body.freshness_days = freshness;

  if (form.scopes.length !== MEMORY_SCOPES.length) {
    body.scopes = MEMORY_SCOPES.filter((s) => form.scopes.includes(s));
  }
  if (!form.includeSources) {
    body.include_sources = false;
  } else if (form.sourceKinds.length !== SOURCE_KINDS.length) {
    body.source_kinds = SOURCE_KINDS.filter((k) => form.sourceKinds.includes(k));
  }
  if (form.maxClassification !== NO_CEILING) {
    body.max_classification = toClassification(Number(form.maxClassification));
  }
  if (form.baseName !== NO_BASE_SNAPSHOT) {
    const version = form.baseVersion === LATEST_VERSION ? undefined : Number.parseInt(form.baseVersion, 10);
    body.base_snapshot = Number.isFinite(version) && version ? { name: form.baseName, version } : { name: form.baseName };
  }
  if (form.saveSnapshot && form.snapshotName.trim()) {
    body.save_snapshot = { name: form.snapshotName.trim() };
  }
  return body;
}

/** Toggle helper that preserves the canonical enum order. */
export function toggleInOrder<T extends string>(values: readonly T[], all: readonly T[], value: T): T[] {
  const set = new Set(values);
  if (set.has(value)) set.delete(value);
  else set.add(value);
  return all.filter((v) => set.has(v));
}

/* -------------------------------------------------------------------------- */
/* Stage timings (waterfall)                                                  */
/* -------------------------------------------------------------------------- */

export interface StageSegment {
  key: ContextStage | "overhead";
  label: string;
  description: string;
  /** Start offset in ms. */
  start: number;
  duration: number;
  /** 0..1 of the total. */
  startRatio: number;
  widthRatio: number;
}

export interface StageWaterfall {
  total: number;
  segments: StageSegment[];
  /** Key of the longest stage (highlighted). */
  slowest: StageSegment["key"] | null;
}

function ms(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

/**
 * Sequential waterfall of the 8 assembly stages. When the reported total exceeds the sum of stages,
 * the remainder (persistence, tracing) is shown as an extra "overhead" segment.
 */
export function buildStageWaterfall(timings: Partial<ContextTimings> | null | undefined): StageWaterfall {
  const t = timings ?? {};
  const durations = CONTEXT_STAGES.map((stage) => ({ stage, duration: ms(t[stage]) }));
  const sum = durations.reduce((acc, d) => acc + d.duration, 0);
  const reportedTotal = ms(t.total);
  const overhead = reportedTotal > sum ? reportedTotal - sum : 0;
  const total = Math.max(reportedTotal, sum);
  const segments: StageSegment[] = [];
  let cursor = 0;
  for (const { stage, duration } of durations) {
    segments.push({
      key: stage,
      label: CONTEXT_STAGE_META[stage].label,
      description: CONTEXT_STAGE_META[stage].description ?? "",
      start: cursor,
      duration,
      startRatio: total > 0 ? cursor / total : 0,
      widthRatio: total > 0 ? duration / total : 0,
    });
    cursor += duration;
  }
  if (overhead >= 0.5) {
    segments.push({
      key: "overhead",
      label: "Persistance",
      description: "Enregistrement des décisions, trace et métriques",
      start: cursor,
      duration: overhead,
      startRatio: total > 0 ? cursor / total : 0,
      widthRatio: total > 0 ? overhead / total : 0,
    });
  }
  let slowest: StageSegment | null = null;
  for (const s of segments) {
    if (s.key !== "overhead" && (!slowest || s.duration > slowest.duration)) slowest = s;
  }
  return { total, segments, slowest: slowest && slowest.duration > 0 ? slowest.key : null };
}

/* -------------------------------------------------------------------------- */
/* Citations                                                                  */
/* -------------------------------------------------------------------------- */

/** DOM id of a retained item card, used by citation links and "related citation" jumps. */
export function citationDomId(citation: string): string {
  return `ctx-item-${citation.replace(/[^A-Za-z0-9_-]/g, "")}`;
}

/** DOM id of an exclusion group in the "Exclus" column. */
export function exclusionGroupDomId(code: string): string {
  return `ctx-excluded-${code.replace(/[^A-Za-z0-9_-]/g, "")}`;
}

const CITATION_GROUP = /\[(S\d+(?:\s*[,;]\s*S\d+)*)\](?!\(|:)/g;

/**
 * Turns `[S1]` / `[S1, S3]` markers into in-page links (`[S1](#orbit-cite-S1)`) so the Markdown renderer
 * can display them as interactive citation badges. Fenced/inline code is left untouched.
 */
export function linkifyCitations(markdown: string): string {
  const parts = markdown.split(/(```[\s\S]*?```|`[^`\n]*`)/g);
  return parts
    .map((part, i) => {
      if (i % 2 === 1) return part; // code span / fence
      return part.replace(CITATION_GROUP, (_match, group: string) =>
        group
          .split(/\s*[,;]\s*/)
          .map((c) => `[${c}](${CITATION_HREF_PREFIX}${c})`)
          .join(" "),
      );
    })
    .join("");
}

const SOURCE_LINE = /^\[(S\d+)\][ \t]+/gm;

/**
 * Prepares the served Markdown for display: the `## Sources` list is emitted as one `[S1] Titre — …` line per
 * citation (a single paragraph in CommonMark), so those lines become list items; citations become links.
 * The raw Markdown (copy / download) is left untouched.
 */
export function renderableContextMarkdown(markdown: string): string {
  const parts = markdown.split(/(```[\s\S]*?```)/g);
  const listed = parts.map((part, i) => (i % 2 === 1 ? part : part.replace(SOURCE_LINE, "- [$1] "))).join("");
  return linkifyCitations(listed);
}

/** Extracts the citation from a generated href, or null. */
export function citationFromHref(href: string | null | undefined): string | null {
  if (!href || !href.startsWith(CITATION_HREF_PREFIX)) return null;
  const c = href.slice(CITATION_HREF_PREFIX.length);
  return /^S\d+$/.test(c) ? c : null;
}

/* -------------------------------------------------------------------------- */
/* Exclusions                                                                 */
/* -------------------------------------------------------------------------- */

export interface ExclusionGroup {
  code: ReasonCode | string;
  items: ExcludedItem[];
  /** Count from `exclusion_summary` when available (agents may receive counters only). */
  count: number;
}

const ORDER_INDEX = new Map<string, number>(REASON_CODE_ORDER.map((c, i) => [c, i]));

function orderOf(code: string): number {
  return ORDER_INDEX.get(code) ?? REASON_CODE_ORDER.length;
}

/** Groups excluded items by reason code (governance order), merging counts from the summary. */
export function groupExclusions(
  excluded: readonly ExcludedItem[],
  summary: Partial<Record<ReasonCode, number>> | null | undefined,
): ExclusionGroup[] {
  const map = new Map<string, ExcludedItem[]>();
  for (const item of excluded) {
    const list = map.get(item.reason_code);
    if (list) list.push(item);
    else map.set(item.reason_code, [item]);
  }
  for (const [code, count] of Object.entries(summary ?? {})) {
    if (typeof count === "number" && count > 0 && !map.has(code)) map.set(code, []);
  }
  return [...map.entries()]
    .map(([code, items]) => {
      const summarized = summary?.[code as ReasonCode];
      return { code, items, count: Math.max(items.length, typeof summarized === "number" ? summarized : 0) };
    })
    .filter((g) => g.count > 0)
    .sort((a, b) => orderOf(a.code) - orderOf(b.code));
}

export interface ExclusionSummaryEntry {
  code: ReasonCode | string;
  count: number;
  ratio: number;
}

/** Summary entries sorted by count (desc), falling back to the excluded list when no summary is present. */
export function exclusionSummaryEntries(
  summary: Partial<Record<ReasonCode, number>> | null | undefined,
  excluded: readonly ExcludedItem[] = [],
): ExclusionSummaryEntry[] {
  const counts = new Map<string, number>();
  for (const [code, count] of Object.entries(summary ?? {})) {
    if (typeof count === "number" && count > 0 && !code.startsWith("INCLUDED_")) counts.set(code, count);
  }
  if (counts.size === 0) {
    for (const item of excluded) counts.set(item.reason_code, (counts.get(item.reason_code) ?? 0) + 1);
  }
  const max = Math.max(0, ...counts.values());
  return [...counts.entries()]
    .map(([code, count]) => ({ code, count, ratio: max > 0 ? count / max : 0 }))
    .sort((a, b) => b.count - a.count || orderOf(a.code) - orderOf(b.code));
}

/* -------------------------------------------------------------------------- */
/* Items & scores                                                             */
/* -------------------------------------------------------------------------- */

export function maxItemClassification(items: ReadonlyArray<{ classification?: number | null }>): Classification {
  return items.reduce<Classification>((max, i) => {
    const c = toClassification(i.classification);
    return c > max ? c : max;
  }, 0);
}

export interface ScoreRow {
  key: keyof Scores;
  label: string;
  hint: string;
  value: number | undefined;
  /** Bar scale (BM25 is unbounded and normalized to the package maximum). */
  max: number;
}

/** Largest BM25 score of a package (≥ 1), used to scale the BM25 bars. */
export function bm25Scale(items: ReadonlyArray<{ scores: Scores }>): number {
  return Math.max(1, ...items.map((i) => (typeof i.scores.bm25 === "number" ? i.scores.bm25 : 0)));
}

export function scoreRows(scores: Scores, bm25Max = 1): ScoreRow[] {
  const val = (v: number | undefined) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
  return [
    { key: "bm25", label: "BM25", hint: "Pertinence lexicale (analyseur français)", value: val(scores.bm25), max: bm25Max },
    { key: "dense", label: "Dense", hint: "Similarité sémantique (embeddings)", value: val(scores.dense), max: 1 },
    { key: "rrf", label: "RRF", hint: "Fusion des rangs BM25 / k-NN, normalisée", value: val(scores.rrf), max: 1 },
    { key: "rerank", label: "Rerank", hint: "Score du reclassement", value: val(scores.rerank), max: 1 },
    { key: "freshness", label: "Fraîcheur", hint: "Décroissance exponentielle, demi-vie 90 j", value: val(scores.freshness), max: 1 },
    { key: "final", label: "Final", hint: "Score retenu pour la sélection", value: val(scores.final), max: 1 },
  ];
}

/** Title of a context item for citation tooltips. */
export function citationTitles(items: readonly ContextItem[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const item of items) out[item.citation] = item.title;
  return out;
}

/** File name for the Markdown download. */
export function contextFilename(slug: string, requestId: string, snapshot?: { name: string; version: number } | null): string {
  if (snapshot) return `contexte-${slug}-${snapshot.name}-v${snapshot.version}.md`;
  return `contexte-${slug}-${requestId.replace(/-/g, "").slice(0, 8)}.md`;
}
