"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Camera, GitBranch, LayoutGrid, Rows3, Search, SearchX, Telescope } from "lucide-react";

import { RelativeTime } from "@/components/domain/relative-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCurrentProject } from "@/hooks/use-current-project";
import { useSnapshots } from "@/lib/api/hooks";
import type { SnapshotListItem } from "@/lib/api/types";
import { formatNumber, plural } from "@/lib/format";
import { normalizeText } from "@/lib/utils";

type Layout = "cards" | "table";
const LAYOUT_KEY = "orbit:snapshots-layout";

function snapshotHref(slug: string, name: string): string {
  return `/projects/${encodeURIComponent(slug)}/snapshots/${encodeURIComponent(name)}`;
}

function SnapshotCard({ slug, snapshot }: { slug: string; snapshot: SnapshotListItem }) {
  return (
    <Link
      href={snapshotHref(slug, snapshot.name)}
      className="group rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Card interactive className="flex h-full flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand ring-1 ring-inset ring-brand/20">
              <Camera className="size-4" aria-hidden />
            </span>
            <span className="truncate font-mono text-[14px] font-semibold text-foreground">{snapshot.name}</span>
          </div>
          <Badge tone="teal" mono size="md">
            v{snapshot.latest_version}
          </Badge>
        </div>
        <p className="line-clamp-2 min-h-[2.5rem] text-[13px] leading-relaxed text-muted-foreground">
          {snapshot.last_task || "Aucune tâche renseignée."}
        </p>
        <div className="mt-auto flex items-center gap-3 border-t border-border pt-3 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <GitBranch className="size-3.5" aria-hidden />
            {plural(snapshot.versions, "version")}
          </span>
          <span>
            mis à jour <RelativeTime date={snapshot.updated_at} />
          </span>
          <ArrowRight
            className="ml-auto size-4 text-subtle-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary"
            aria-hidden
          />
        </div>
      </Card>
    </Link>
  );
}

function SnapshotTable({ slug, snapshots }: { slug: string; snapshots: readonly SnapshotListItem[] }) {
  const router = useRouter();
  return (
    <Card className="overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Nom</TableHead>
            <TableHead className="w-28">Dernière version</TableHead>
            <TableHead className="w-24 text-right">Versions</TableHead>
            <TableHead>Dernière tâche</TableHead>
            <TableHead className="w-36">Mis à jour</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {snapshots.map((s) => (
            <TableRow
              key={s.name}
              interactive
              tabIndex={0}
              onClick={() => router.push(snapshotHref(slug, s.name))}
              onKeyDown={(e) => {
                if (e.key === "Enter") router.push(snapshotHref(slug, s.name));
              }}
            >
              <TableCell>
                <Link
                  href={snapshotHref(slug, s.name)}
                  className="inline-flex items-center gap-2 font-mono font-semibold text-foreground hover:text-primary"
                  onClick={(e) => e.stopPropagation()}
                >
                  <Camera className="size-3.5 text-brand" aria-hidden />
                  {s.name}
                </Link>
              </TableCell>
              <TableCell>
                <Badge tone="teal" mono>
                  v{s.latest_version}
                </Badge>
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(s.versions, 0)}</TableCell>
              <TableCell className="max-w-md">
                <span className="line-clamp-1 text-muted-foreground" title={s.last_task}>
                  {s.last_task || "—"}
                </span>
              </TableCell>
              <TableCell className="text-muted-foreground">
                <RelativeTime date={s.updated_at} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

/** Snapshots list: lineages of shared, versioned context (cards or table). */
export function SnapshotListView() {
  const { slug } = useCurrentProject();
  const snapshots = useSnapshots(slug);
  const [query, setQuery] = React.useState("");
  const [layout, setLayout] = React.useState<Layout>("cards");

  React.useEffect(() => {
    try {
      const stored = window.localStorage.getItem(LAYOUT_KEY);
      if (stored === "cards" || stored === "table") setLayout(stored);
    } catch {
      // storage unavailable
    }
  }, []);

  const changeLayout = (next: Layout) => {
    setLayout(next);
    try {
      window.localStorage.setItem(LAYOUT_KEY, next);
    } catch {
      // storage unavailable
    }
  };

  const list = React.useMemo(() => {
    const items = [...(snapshots.data ?? [])].sort(
      (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    );
    const q = normalizeText(query);
    return q ? items.filter((s) => normalizeText(`${s.name} ${s.last_task}`).includes(q)) : items;
  }, [snapshots.data, query]);

  const totalVersions = (snapshots.data ?? []).reduce((sum, s) => sum + s.versions, 0);
  const hasSnapshots = (snapshots.data?.length ?? 0) > 0;
  const explorerHref = `/projects/${encodeURIComponent(slug)}/explorer`;

  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader
        icon={<Camera />}
        title="Snapshots"
        description="Contextes partagés, versionnés et immuables : un agent design ou engineering repart exactement du contexte validé par l'agent produit."
        meta={
          hasSnapshots ? (
            <>
              <Badge tone="teal" size="md">
                {plural(snapshots.data?.length ?? 0, "snapshot")}
              </Badge>
              <Badge tone="neutral" variant="outline" size="md">
                {plural(totalVersions, "version")}
              </Badge>
            </>
          ) : null
        }
        actions={
          <Button asChild variant="secondary">
            <Link href={explorerHref}>
              <Telescope aria-hidden />
              Créer depuis l&apos;explorateur
            </Link>
          </Button>
        }
        className="pb-0"
      />

      {snapshots.isError ? (
        <ErrorState error={snapshots.error} onRetry={() => void snapshots.refetch()} />
      ) : snapshots.isPending ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true" aria-label="Chargement des snapshots">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-40 rounded-xl" />
          ))}
        </div>
      ) : !hasSnapshots ? (
        <EmptyState
          size="lg"
          icon={<Camera />}
          title="Aucun snapshot pour l'instant"
          description="Dans l'explorateur de contexte, activez « Enregistrer comme snapshot » pour figer un contexte (par ex. spec-atlas) et le partager entre agents, version après version."
          action={
            <Button asChild>
              <Link href={explorerHref}>
                <Telescope aria-hidden />
                Ouvrir l&apos;explorateur
              </Link>
            </Button>
          }
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <Input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filtrer par nom ou tâche…"
              aria-label="Filtrer les snapshots"
              leftIcon={<Search aria-hidden />}
              className="w-full sm:max-w-sm"
            />
            <SegmentedControl<Layout>
              value={layout}
              onValueChange={changeLayout}
              aria-label="Présentation"
              className="ml-auto"
              options={[
                { value: "cards", label: "Cartes", icon: <LayoutGrid aria-hidden /> },
                { value: "table", label: "Tableau", icon: <Rows3 aria-hidden /> },
              ]}
            />
          </div>
          {list.length === 0 ? (
            <EmptyState
              icon={<SearchX />}
              title="Aucun snapshot ne correspond"
              description="Essayez un autre nom ou une autre formulation de tâche."
              action={
                <Button variant="secondary" size="sm" onClick={() => setQuery("")}>
                  Effacer le filtre
                </Button>
              }
            />
          ) : layout === "cards" ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {list.map((s) => (
                <SnapshotCard key={s.name} slug={slug} snapshot={s} />
              ))}
            </div>
          ) : (
            <SnapshotTable slug={slug} snapshots={list} />
          )}
        </>
      )}
    </div>
  );
}
