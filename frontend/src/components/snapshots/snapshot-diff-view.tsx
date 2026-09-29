"use client";

import * as React from "react";
import { ArrowLeftRight, ArrowRight, ChevronDown, ChevronUp, Equal, GitCompareArrows, Minus, Plus } from "lucide-react";

import { CandidateTypeBadge } from "@/components/domain/enum-badge";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useSnapshotDiff } from "@/lib/api/hooks";
import type { SnapshotItem, SnapshotSummary } from "@/lib/api/types";
import { formatDate, formatNumber, plural } from "@/lib/format";
import { cn } from "@/lib/utils";

import { CitationTag, SnapshotItemNature, SnapshotItemTitle } from "./snapshot-items-table";
import { sortByCitation } from "./snapshot-utils";

type DiffKind = "added" | "removed" | "unchanged";

const KIND_STYLES: Record<DiffKind, { row: string; icon: React.ReactNode; label: string; chip: string }> = {
  added: {
    row: "border-l-emerald-500 bg-emerald-50/60 dark:border-l-emerald-400 dark:bg-emerald-400/5",
    icon: <Plus className="size-3.5 text-emerald-600 dark:text-emerald-400" aria-hidden />,
    label: "Ajoutés",
    chip: "bg-emerald-50 text-emerald-800 ring-emerald-600/20 dark:bg-emerald-400/10 dark:text-emerald-300 dark:ring-emerald-400/25",
  },
  removed: {
    row: "border-l-red-500 bg-red-50/60 dark:border-l-red-400 dark:bg-red-400/5",
    icon: <Minus className="size-3.5 text-red-600 dark:text-red-400" aria-hidden />,
    label: "Retirés",
    chip: "bg-red-50 text-red-800 ring-red-600/20 dark:bg-red-400/10 dark:text-red-300 dark:ring-red-400/25",
  },
  unchanged: {
    row: "border-l-border-strong bg-card",
    icon: <Equal className="size-3.5 text-muted-foreground" aria-hidden />,
    label: "Inchangés",
    chip: "bg-slate-100 text-slate-700 ring-slate-500/15 dark:bg-slate-400/10 dark:text-slate-300 dark:ring-slate-400/20",
  },
};

function DiffRow({ slug, item, kind }: { slug: string; item: SnapshotItem; kind: DiffKind }) {
  const style = KIND_STYLES[kind];
  return (
    <li className={cn("grid grid-cols-[auto_minmax(0,1fr)] gap-3 rounded-lg border border-border border-l-[3px] p-3", style.row)}>
      <div className="flex items-center gap-2 pt-0.5">
        {style.icon}
        <CitationTag citation={item.citation} forgotten={item.forgotten} />
      </div>
      <div className="grid min-w-0 gap-1.5">
        <div className={cn("text-[13px]", kind === "removed" && "[&_a]:line-through [&_span.font-medium]:line-through")}>
          <SnapshotItemTitle slug={slug} item={item} />
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <CandidateTypeBadge value={item.candidate_type} />
          <SnapshotItemNature item={item} />
          {item.version ? <span className="font-mono">v{item.version}</span> : null}
        </div>
      </div>
    </li>
  );
}

function DiffSection({
  slug,
  kind,
  items,
  collapsible = false,
}: {
  slug: string;
  kind: DiffKind;
  items: readonly SnapshotItem[];
  collapsible?: boolean;
}) {
  const [open, setOpen] = React.useState(!collapsible);
  const style = KIND_STYLES[kind];
  const sorted = React.useMemo(() => sortByCitation(items), [items]);
  return (
    <section className="grid gap-2" aria-label={style.label}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-[13px] font-semibold">
          {style.icon}
          {style.label}
          <span className={cn("rounded px-1.5 py-px text-[11px] font-semibold tabular-nums ring-1 ring-inset", style.chip)}>
            {formatNumber(items.length, 0)}
          </span>
        </h3>
        {collapsible && items.length > 0 ? (
          <Button
            variant="ghost"
            size="xs"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            leftIcon={open ? <ChevronUp aria-hidden /> : <ChevronDown aria-hidden />}
          >
            {open ? "Masquer" : `Afficher ${plural(items.length, "élément inchangé", "éléments inchangés")}`}
          </Button>
        ) : null}
      </div>
      {items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-3 py-2.5 text-xs text-muted-foreground">
          {kind === "added" ? "Aucun élément ajouté." : kind === "removed" ? "Aucun élément retiré." : "Aucun élément commun."}
        </p>
      ) : open ? (
        <ul className="grid gap-2">
          {sorted.map((item) => (
            <DiffRow key={item.key} slug={slug} item={item} kind={kind} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export interface SnapshotDiffViewProps {
  slug: string;
  name: string;
  versions: readonly SnapshotSummary[];
  from: number;
  to: number;
  onChange: (from: number, to: number) => void;
}

/** Compare two versions of a snapshot: added (green), removed (red), unchanged (collapsed). */
export function SnapshotDiffView({ slug, name, versions, from, to, onChange }: SnapshotDiffViewProps) {
  const diff = useSnapshotDiff(slug, name, from, to);
  const options = React.useMemo(
    () =>
      versions.map((v) => ({
        value: String(v.version),
        label: `v${v.version}`,
        description: `${formatDate(v.created_at)}${v.created_by_label ? ` · ${v.created_by_label}` : ""}`,
      })),
    [versions],
  );
  const fromMeta = versions.find((v) => v.version === from);
  const toMeta = versions.find((v) => v.version === to);

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end gap-2 rounded-xl border border-border bg-card p-3 shadow-xs">
        <div className="grid gap-1">
          <span className="text-[11px] font-medium uppercase tracking-wide text-subtle-foreground">Depuis</span>
          <SimpleSelect
            value={String(from)}
            onValueChange={(v) => onChange(Number(v), to)}
            options={options}
            size="sm"
            className="w-44"
            aria-label="Version de départ"
          />
        </div>
        <ArrowRight className="mb-2 size-4 text-muted-foreground" aria-hidden />
        <div className="grid gap-1">
          <span className="text-[11px] font-medium uppercase tracking-wide text-subtle-foreground">Vers</span>
          <SimpleSelect
            value={String(to)}
            onValueChange={(v) => onChange(from, Number(v))}
            options={options}
            size="sm"
            className="w-44"
            aria-label="Version d'arrivée"
          />
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onChange(to, from)}
          leftIcon={<ArrowLeftRight aria-hidden />}
          className="mb-px"
        >
          Inverser
        </Button>
        {fromMeta && toMeta ? (
          <p className="ml-auto self-center text-xs text-muted-foreground">
            {formatNumber(fromMeta.items_count, 0)} → {formatNumber(toMeta.items_count, 0)} éléments ·{" "}
            {formatNumber(fromMeta.token_count, 0)} → {formatNumber(toMeta.token_count, 0)} tokens
          </p>
        ) : null}
      </div>

      {from === to ? (
        <Alert tone="blue" title="Choisissez deux versions différentes">
          Sélectionnez une version de départ et une version d&apos;arrivée pour afficher les éléments ajoutés, retirés et
          inchangés.
        </Alert>
      ) : diff.isPending ? (
        <div className="grid gap-3" aria-busy="true" aria-label="Calcul des différences">
          <div className="flex gap-2">
            {Array.from({ length: 3 }, (_, i) => (
              <Skeleton key={i} className="h-16 flex-1 rounded-xl" />
            ))}
          </div>
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
      ) : diff.isError ? (
        <ErrorState error={diff.error} onRetry={() => void diff.refetch()} />
      ) : (
        <>
          <div className="grid grid-cols-3 gap-2">
            {(["added", "removed", "unchanged"] as const).map((kind) => (
              <div key={kind} className={cn("grid gap-0.5 rounded-xl p-3 ring-1 ring-inset", KIND_STYLES[kind].chip)}>
                <span className="flex items-center gap-1.5 text-xs font-medium">
                  {KIND_STYLES[kind].icon}
                  {KIND_STYLES[kind].label}
                </span>
                <span className="text-xl font-semibold tabular-nums">{formatNumber(diff.data[kind].length, 0)}</span>
              </div>
            ))}
          </div>
          {diff.data.added.length === 0 && diff.data.removed.length === 0 ? (
            <EmptyState
              size="sm"
              icon={<GitCompareArrows />}
              title="Aucune différence d'éléments"
              description={`v${from} et v${to} référencent exactement les mêmes éléments de contexte.`}
            />
          ) : null}
          <DiffSection slug={slug} kind="added" items={diff.data.added} />
          <DiffSection slug={slug} kind="removed" items={diff.data.removed} />
          <DiffSection slug={slug} kind="unchanged" items={diff.data.unchanged} collapsible />
        </>
      )}
    </div>
  );
}
