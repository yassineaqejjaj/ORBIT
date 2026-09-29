/** Pure helpers for the Snapshots screens. */
import type { SnapshotItem, SnapshotSummary } from "@/lib/api/types";

/** "sha256:9f2c…" → "9f2c4be1a0". */
export function shortHash(hash: string | null | undefined, length = 10): string {
  if (!hash) return "—";
  const raw = hash.includes(":") ? hash.slice(hash.indexOf(":") + 1) : hash;
  return raw.slice(0, length);
}

export const CITATION_HREF_PREFIX = "#cite-";

const CITATION_PATTERN = /\[(S\d{1,4})\](?!\()/g;

/**
 * Turns bare citations `[S1]` into Markdown links `[S1](#cite-S1)` so the renderer can style them as
 * badges. Fenced code blocks and inline code spans are left untouched.
 */
export function linkCitations(markdown: string): string {
  return markdown
    .split(/(```[\s\S]*?```)/g)
    .map((segment, index) => {
      if (index % 2 === 1) return segment; // fenced code block
      return segment
        .split(/(`[^`\n]*`)/g)
        .map((part, i) => (i % 2 === 1 ? part : part.replace(CITATION_PATTERN, `[$1](${CITATION_HREF_PREFIX}$1)`)))
        .join("");
    })
    .join("");
}

/** Numeric order of a citation ("S12" → 12), unknown citations last. */
export function citationOrder(citation: string | null | undefined): number {
  const match = /^S(\d+)$/.exec(citation ?? "");
  return match ? Number(match[1]) : Number.MAX_SAFE_INTEGER;
}

export function sortByCitation<T extends Pick<SnapshotItem, "citation">>(items: readonly T[]): T[] {
  return [...items].sort((a, b) => citationOrder(a.citation) - citationOrder(b.citation));
}

/** Link to the context explorer using a snapshot version as the base context. */
export function explorerBaseHref(slug: string, name: string, version: number): string {
  const params = new URLSearchParams({ base: name, version: String(version) });
  return `/projects/${encodeURIComponent(slug)}/explorer?${params.toString()}`;
}

/** Versions sorted from the most recent to the oldest. */
export function sortVersionsDesc(versions: readonly SnapshotSummary[]): SnapshotSummary[] {
  return [...versions].sort((a, b) => b.version - a.version);
}
