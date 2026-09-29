/**
 * Pure helpers for the Mémoire screens (no React): status predicates, allowed actions,
 * version diffs and a small word-level diff used by the history timeline.
 */
import type { MemoryEvent, MemoryItem, Relation } from "@/lib/api/types";
import {
  CLASSIFICATION_META,
  getMeta,
  MEMORY_KIND_META,
  toClassification,
  type MemoryScope,
  type MemoryStatus,
} from "@/lib/enums";
import { formatDate, formatDateLong } from "@/lib/format";

/** Statuses rendered dimmed (no longer served to agents as-is). */
export const INACTIVE_STATUSES: ReadonlySet<MemoryStatus> = new Set(["superseded", "obsolete", "forgotten"]);

export function isInactive(item: Pick<MemoryItem, "status">): boolean {
  return INACTIVE_STATUSES.has(item.status);
}

/** Scopes a human can create from the UI (short_term needs a session id). */
export const CREATABLE_SCOPES: readonly MemoryScope[] = ["project", "user", "long_term", "short_term"];

export interface MemoryPermissions {
  canEdit: boolean;
  isOwner: boolean;
  meId: string | null | undefined;
}

export interface MemoryActionAvailability {
  validate: boolean;
  obsolete: boolean;
  edit: boolean;
  supersede: boolean;
  restore: boolean;
  forget: boolean;
}

/** Which lifecycle actions make sense for `item` given the caller's rights (UI only; the API enforces). */
export function availableActions(item: MemoryItem, perms: MemoryPermissions): MemoryActionAvailability {
  const current = item.is_current;
  const forgotten = item.status === "forgotten";
  const editor = perms.canEdit && current && !forgotten;
  const isSubject = item.scope === "user" && Boolean(perms.meId) && item.subject_user_id === perms.meId;
  return {
    validate: editor && item.status === "proposed",
    obsolete: editor && (item.status === "proposed" || item.status === "validated"),
    edit: editor && (item.status === "proposed" || item.status === "validated"),
    supersede: editor && (item.status === "proposed" || item.status === "validated"),
    restore: editor && (item.status === "superseded" || item.status === "obsolete"),
    forget: current && !forgotten && (perms.isOwner || isSubject),
  };
}

/** "C2 · Confidentiel" */
export function classificationLabel(level: number | null | undefined): string {
  const meta = CLASSIFICATION_META[toClassification(level)];
  return `${meta.code} · ${meta.label}`;
}

/** Validity window label: "depuis le 2 sept. 2026", "du 2 sept. 2026 au 15 nov. 2026". */
export function validityLabel(item: Pick<MemoryItem, "valid_from" | "valid_to">): string {
  if (item.valid_to) return `du ${formatDate(item.valid_from)} au ${formatDate(item.valid_to)}`;
  return `depuis le ${formatDate(item.valid_from)} · sans échéance`;
}

/** True when `valid_to` is in the past. */
export function isExpired(item: Pick<MemoryItem, "valid_to" | "expires_at">, now: Date = new Date()): boolean {
  const limit = item.valid_to ?? item.expires_at;
  return Boolean(limit) && new Date(limit as string).getTime() < now.getTime();
}

/** Relation that explains who superseded this item (incoming `supersedes`). */
export function supersededByRelation(relations: readonly Relation[]): Relation | undefined {
  return relations.find((r) => r.rel_type === "supersedes" && r.direction === "in" && r.other_type === "memory");
}

/** Relation that explains which item this one replaces (outgoing `supersedes`). */
export function supersedesRelation(relations: readonly Relation[]): Relation | undefined {
  return relations.find((r) => r.rel_type === "supersedes" && r.direction === "out" && r.other_type === "memory");
}

/* -------------------------------------------------------------------------- */
/* Version diffs                                                              */
/* -------------------------------------------------------------------------- */

export type DiffField = "title" | "content" | "kind" | "classification" | "valid_to" | "tags" | "status";

export interface FieldChange {
  field: DiffField | string;
  label: string;
  before: string;
  after: string;
  /** Long text: render a word-level diff instead of before → after. */
  long: boolean;
}

const FIELD_LABELS: Record<string, string> = {
  title: "Titre",
  content: "Contenu",
  kind: "Nature",
  classification: "Classification",
  valid_to: "Fin de validité",
  valid_from: "Début de validité",
  tags: "Étiquettes",
  status: "Statut",
  confidence: "Confiance",
};

function displayValue(field: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (field === "kind") return getMeta(MEMORY_KIND_META, String(value)).label;
  if (field === "classification") return classificationLabel(Number(value));
  if (field === "valid_to" || field === "valid_from") return formatDateLong(String(value));
  if (field === "confidence" && typeof value === "number") return value.toFixed(2).replace(".", ",");
  if (Array.isArray(value)) return value.length ? value.map(String).join(", ") : "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function change(field: string, before: unknown, after: unknown): FieldChange {
  return {
    field,
    label: FIELD_LABELS[field] ?? field,
    before: displayValue(field, before),
    after: displayValue(field, after),
    long: field === "content",
  };
}

/** Field-level changes between two versions of the same lineage. */
export function diffVersions(prev: MemoryItem, next: MemoryItem): FieldChange[] {
  const out: FieldChange[] = [];
  if (prev.title !== next.title) out.push(change("title", prev.title, next.title));
  if (prev.content !== next.content) out.push(change("content", prev.content, next.content));
  if (prev.kind !== next.kind) out.push(change("kind", prev.kind, next.kind));
  if (prev.classification !== next.classification)
    out.push(change("classification", prev.classification, next.classification));
  if ((prev.valid_to ?? null) !== (next.valid_to ?? null)) out.push(change("valid_to", prev.valid_to, next.valid_to));
  if (prev.tags.join("\u0000") !== next.tags.join("\u0000")) out.push(change("tags", prev.tags, next.tags));
  return out;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Changes recorded by the backend in `event.data` (tolerant to several shapes):
 * `{changes: {field: {from, to}}}`, `{changes: {field: [from, to]}}`, `{before: {...}, after: {...}}`.
 */
export function changesFromEventData(data: MemoryEvent["data"]): FieldChange[] {
  if (!isRecord(data)) return [];
  const out: FieldChange[] = [];
  const changes = data.changes;
  if (isRecord(changes)) {
    for (const [field, value] of Object.entries(changes)) {
      if (Array.isArray(value) && value.length === 2) out.push(change(field, value[0], value[1]));
      else if (isRecord(value) && ("from" in value || "to" in value || "old" in value || "new" in value)) {
        out.push(change(field, value.from ?? value.old, value.to ?? value.new));
      } else if (isRecord(value) && ("before" in value || "after" in value)) {
        out.push(change(field, value.before, value.after));
      }
    }
    return out;
  }
  const before = data.before;
  const after = data.after;
  if (isRecord(before) && isRecord(after)) {
    const fields = new Set([...Object.keys(before), ...Object.keys(after)]);
    for (const field of fields) {
      if (JSON.stringify(before[field]) !== JSON.stringify(after[field])) out.push(change(field, before[field], after[field]));
    }
  }
  return out;
}

/**
 * Changes introduced by an `edited` event: from `event.data` when the backend recorded them,
 * otherwise computed from the lineage versions (event.memory_item_id = the version it created).
 */
export function changesForEvent(event: MemoryEvent, versions: readonly MemoryItem[]): FieldChange[] {
  const recorded = changesFromEventData(event.data);
  if (recorded.length > 0) return recorded;
  const next = versions.find((v) => v.id === event.memory_item_id);
  if (!next) return [];
  const prev = versions.find((v) => v.version === next.version - 1);
  return prev ? diffVersions(prev, next) : [];
}

/* -------------------------------------------------------------------------- */
/* Word diff                                                                  */
/* -------------------------------------------------------------------------- */

export type DiffOp = { type: "equal" | "insert" | "delete"; text: string };

const MAX_DIFF_CELLS = 400_000;

/** Word-level diff (LCS). Returns null when the texts are too large to diff interactively. */
export function wordDiff(before: string, after: string): DiffOp[] | null {
  const a = before.split(/(\s+)/).filter((t) => t.length > 0);
  const b = after.split(/(\s+)/).filter((t) => t.length > 0);
  const n = a.length;
  const m = b.length;
  if (n * m > MAX_DIFF_CELLS) return null;

  // LCS lengths, row-major (n+1) x (m+1).
  const width = m + 1;
  const table = new Uint32Array((n + 1) * width);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      table[i * width + j] =
        a[i] === b[j]
          ? (table[(i + 1) * width + j + 1] ?? 0) + 1
          : Math.max(table[(i + 1) * width + j] ?? 0, table[i * width + j + 1] ?? 0);
    }
  }

  const ops: DiffOp[] = [];
  const push = (type: DiffOp["type"], text: string) => {
    const last = ops[ops.length - 1];
    if (last && last.type === type) last.text += text;
    else ops.push({ type, text });
  };
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    const ai = a[i] as string;
    const bj = b[j] as string;
    if (ai === bj) {
      push("equal", ai);
      i++;
      j++;
    } else if ((table[(i + 1) * width + j] ?? 0) >= (table[i * width + j + 1] ?? 0)) {
      push("delete", ai);
      i++;
    } else {
      push("insert", bj);
      j++;
    }
  }
  while (i < n) push("delete", a[i++] as string);
  while (j < m) push("insert", b[j++] as string);
  return ops;
}
