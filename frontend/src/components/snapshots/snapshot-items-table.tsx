"use client";

import * as React from "react";
import Link from "next/link";
import { EyeOff, Layers, Lock } from "lucide-react";

import { CandidateTypeBadge } from "@/components/domain/enum-badge";
import { MemoryKindBadge } from "@/components/domain/memory-kind-badge";
import { SourceKindIcon } from "@/components/domain/source-kind-icon";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { SnapshotItem } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { sortByCitation } from "./snapshot-utils";

export function CitationTag({ citation, forgotten = false }: { citation: string; forgotten?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded px-1.5 font-mono text-[11px] font-semibold ring-1 ring-inset",
        forgotten
          ? "bg-red-50 text-red-700 ring-red-600/25 dark:bg-red-400/10 dark:text-red-300"
          : "bg-teal-50 text-teal-800 ring-teal-600/25 dark:bg-teal-400/10 dark:text-teal-300 dark:ring-teal-400/30",
      )}
    >
      {citation || "—"}
    </span>
  );
}

export function SnapshotItemNature({ item }: { item: SnapshotItem }) {
  if (item.memory_kind) return <MemoryKindBadge kind={item.memory_kind} />;
  if (item.source_kind) return <SourceKindIcon kind={item.source_kind} withLabel size="sm" />;
  return <span className="text-muted-foreground">—</span>;
}

/** True when the API redacted the item for the caller (no id: access or classification not granted). */
export function isRestrictedItem(item: SnapshotItem): boolean {
  return !item.forgotten && !item.id;
}

/** Title cell: forgotten and restricted items are redacted, memory items link to the memory explorer. */
export function SnapshotItemTitle({ slug, item }: { slug: string; item: SnapshotItem }) {
  if (item.forgotten) {
    return (
      <span className="grid gap-0.5">
        <span className="font-medium text-muted-foreground line-through">Élément oublié</span>
        <span className="text-xs italic text-muted-foreground">Contenu oublié — masqué à l&apos;affichage.</span>
      </span>
    );
  }
  if (isRestrictedItem(item)) {
    return (
      <span className="grid gap-0.5">
        <span className="inline-flex items-center gap-1.5 font-medium text-muted-foreground">
          <Lock className="size-3.5 shrink-0" aria-hidden />
          {item.title || "Contenu restreint"}
        </span>
        <span className="text-xs italic text-muted-foreground">
          Vos droits d&apos;accès ou votre habilitation ne permettent pas d&apos;afficher cet élément.
        </span>
      </span>
    );
  }
  const title =
    item.candidate_type === "memory" ? (
      <Link
        href={`/projects/${encodeURIComponent(slug)}/memory?item=${encodeURIComponent(item.id)}`}
        className="font-medium text-foreground hover:text-primary hover:underline"
      >
        {item.title}
      </Link>
    ) : (
      <span className="font-medium text-foreground">{item.title}</span>
    );
  return (
    <span className="grid gap-0.5">
      {title}
      {item.excerpt ? <span className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{item.excerpt}</span> : null}
    </span>
  );
}

export interface SnapshotItemsTableProps {
  slug: string;
  items: readonly SnapshotItem[];
  /** Row to highlight (e.g. after clicking a citation in the content). */
  highlight?: string | null;
}

/** Items pinned by a snapshot version, ordered by citation. */
export function SnapshotItemsTable({ slug, items, highlight }: SnapshotItemsTableProps) {
  const rows = React.useMemo(() => sortByCitation(items), [items]);
  const containerRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!highlight) return;
    const row = containerRef.current?.querySelector<HTMLElement>(`[data-citation="${CSS.escape(highlight)}"]`);
    row?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [highlight]);

  if (rows.length === 0) {
    return (
      <EmptyState
        size="sm"
        icon={<Layers />}
        title="Aucun élément épinglé"
        description="Cette version ne référence aucun élément de contexte."
      />
    );
  }

  return (
    <div ref={containerRef} className="overflow-hidden rounded-xl border border-border bg-card">
      <Table containerClassName="max-h-[36rem]">
        <TableHeader>
          <TableRow>
            <TableHead className="w-16">Citation</TableHead>
            <TableHead className="w-36">Type</TableHead>
            <TableHead>Titre</TableHead>
            <TableHead className="w-40">Nature / source</TableHead>
            <TableHead className="w-20 text-right">Version</TableHead>
            <TableHead className="w-28">État</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((item) => (
            <TableRow
              key={item.key}
              data-citation={item.citation}
              selected={highlight === item.citation}
              className={cn(item.forgotten && "bg-red-50/40 dark:bg-red-400/5")}
            >
              <TableCell>
                <CitationTag citation={item.citation} forgotten={item.forgotten} />
              </TableCell>
              <TableCell>
                <CandidateTypeBadge value={item.candidate_type} />
              </TableCell>
              <TableCell className="min-w-64">
                <SnapshotItemTitle slug={slug} item={item} />
              </TableCell>
              <TableCell>
                <SnapshotItemNature item={item} />
              </TableCell>
              <TableCell className="text-right font-mono text-xs tabular-nums">
                {item.version ? `v${item.version}` : "—"}
              </TableCell>
              <TableCell>
                {item.forgotten ? (
                  <Badge tone="red" icon={<EyeOff aria-hidden />}>
                    Oublié
                  </Badge>
                ) : isRestrictedItem(item) ? (
                  <Badge tone="violet" icon={<Lock aria-hidden />}>
                    Restreint
                  </Badge>
                ) : (
                  <Badge tone="green" dot>
                    Actif
                  </Badge>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
