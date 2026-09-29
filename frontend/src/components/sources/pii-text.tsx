import * as React from "react";

import type { PiiEntity } from "@/lib/api/types";
import { getMeta, PII_TYPE_META } from "@/lib/enums";
import { cn } from "@/lib/utils";

interface Span {
  start: number;
  end: number;
  entity: PiiEntity;
}

/**
 * Resolves PII entities to non-overlapping spans of `text`. Offsets are trusted when they are in range
 * (and match `entity.text` when present); otherwise `entity.text` is searched after the previous span.
 */
export function resolvePiiSpans(text: string, pii: readonly PiiEntity[]): Span[] {
  const sorted = [...pii].sort((a, b) => a.start - b.start || b.end - a.end);
  const spans: Span[] = [];
  let cursor = 0;
  for (const entity of sorted) {
    let { start, end } = entity;
    const inRange = Number.isInteger(start) && Number.isInteger(end) && start >= 0 && end > start && end <= text.length;
    const matches = inRange && (!entity.text || text.slice(start, end) === entity.text);
    if (!matches) {
      if (!entity.text) continue;
      const found = text.indexOf(entity.text, cursor);
      if (found < 0) continue;
      start = found;
      end = found + entity.text.length;
    }
    if (start < cursor) continue; // overlapping span: keep the first one
    spans.push({ start, end, entity });
    cursor = end;
  }
  return spans;
}

const MARK_CLASSES =
  "rounded-[3px] bg-pink-100 px-0.5 text-pink-950 ring-1 ring-inset ring-pink-300 dark:bg-pink-400/20 dark:text-pink-100 dark:ring-pink-400/40";

/** Original text with detected personal data highlighted (editors only). */
export function PiiHighlightedText({ text, pii, className }: { text: string; pii: readonly PiiEntity[]; className?: string }) {
  const spans = React.useMemo(() => resolvePiiSpans(text, pii), [text, pii]);
  const parts: React.ReactNode[] = [];
  let last = 0;
  spans.forEach((span, i) => {
    if (span.start > last) parts.push(text.slice(last, span.start));
    const label = getMeta(PII_TYPE_META, span.entity.type).label;
    parts.push(
      <mark
        key={`pii-${i}`}
        className={MARK_CLASSES}
        title={`${label} — donnée personnelle, caviardée dans le contexte servi aux agents`}
        aria-label={`${label} : ${text.slice(span.start, span.end)}`}
      >
        {text.slice(span.start, span.end)}
      </mark>,
    );
    last = span.end;
  });
  if (last < text.length) parts.push(text.slice(last));
  return <p className={cn("whitespace-pre-wrap break-words", className)}>{parts}</p>;
}

const PLACEHOLDER_RE = /\[[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ_ ]*[A-ZÀ-ÖØ-Þ]\]/g;

/** Redacted text (what agents receive), with the `[EMAIL]`, `[TÉLÉPHONE]`… placeholders emphasized. */
export function RedactedText({ text, className }: { text: string; className?: string }) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const match of text.matchAll(PLACEHOLDER_RE)) {
    const start = match.index ?? 0;
    if (start > last) parts.push(text.slice(last, start));
    parts.push(
      <span
        key={`red-${i++}`}
        className="rounded-[3px] bg-slate-900 px-1 font-mono text-[11.5px] font-medium text-white dark:bg-slate-200 dark:text-slate-900"
        title="Donnée personnelle caviardée"
      >
        {match[0]}
      </span>,
    );
    last = start + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <p className={cn("whitespace-pre-wrap break-words", className)}>{parts}</p>;
}
