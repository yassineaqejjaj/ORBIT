"use client";

import * as React from "react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  Camera,
  Check,
  Coins,
  Copy,
  FileText,
  Fingerprint,
  GitCompareArrows,
  Layers,
  Rocket,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";

import { IntentBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCurrentProject } from "@/hooks/use-current-project";
import { useSnapshot, useSnapshotVersions } from "@/lib/api/hooks";
import type { Snapshot, SnapshotSummary } from "@/lib/api/types";
import { formatDate, formatDateTime, formatNumber, formatTokens, plural } from "@/lib/format";
import { copyToClipboard } from "@/lib/utils";

import { SnapshotDiffView } from "./snapshot-diff-view";
import { SnapshotItemsTable } from "./snapshot-items-table";
import { SnapshotMarkdown } from "./snapshot-markdown";
import { explorerBaseHref, shortHash, sortVersionsDesc } from "./snapshot-utils";
import { SnapshotVersionTimeline, SnapshotVersionTimelineSkeleton } from "./snapshot-version-timeline";

type Mode = "view" | "compare";
type ContentTab = "content" | "items";

function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function parsePositiveInt(value: string | null): number | null {
  if (!value) return null;
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** URL state: `?v=3`, `?mode=compare&from=2&to=3`, `?tab=items`. */
function useSnapshotUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const raw = searchParams.toString();
  const state = React.useMemo(() => {
    const params = new URLSearchParams(raw);
    return {
      version: parsePositiveInt(params.get("v")),
      mode: (params.get("mode") === "compare" ? "compare" : "view") as Mode,
      from: parsePositiveInt(params.get("from")),
      to: parsePositiveInt(params.get("to")),
      tab: (params.get("tab") === "items" ? "items" : "content") as ContentTab,
    };
  }, [raw]);

  const update = React.useCallback(
    (patch: Record<string, string | number | null>) => {
      const params = new URLSearchParams(raw);
      for (const [key, value] of Object.entries(patch)) {
        if (value === null || value === "") params.delete(key);
        else params.set(key, String(value));
      }
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [raw, pathname, router],
  );
  return [state, update] as const;
}

function CopyContentButton({ content }: { content: string | undefined }) {
  const [copied, setCopied] = React.useState(false);
  React.useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(t);
  }, [copied]);
  return (
    <Button
      variant="secondary"
      disabled={!content}
      onClick={async () => {
        if (!content) return;
        const ok = await copyToClipboard(content);
        if (ok) {
          setCopied(true);
          toast.success("Contenu copié", { description: "Le contexte Markdown est dans le presse-papiers." });
        } else {
          toast.error("Impossible de copier le contenu dans le presse-papiers.");
        }
      }}
      leftIcon={copied ? <Check aria-hidden /> : <Copy aria-hidden />}
    >
      {copied ? "Copié" : "Copier le contenu"}
    </Button>
  );
}

function VersionSummaryCard({ summary, snapshot }: { summary: SnapshotSummary; snapshot: Snapshot | undefined }) {
  return (
    <div className="grid gap-3 rounded-xl border border-border bg-card p-4 shadow-xs">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[15px] font-semibold tracking-tight">Version {summary.version}</h2>
        <IntentBadge value={summary.intent} />
        {summary.parent_version ? (
          <Badge variant="outline" tone="neutral">
            dérivée de v{summary.parent_version}
          </Badge>
        ) : null}
        <span className="ml-auto text-xs text-muted-foreground" title={formatDateTime(summary.created_at)}>
          <RelativeTime date={summary.created_at} />
        </span>
      </div>
      <p className="text-[13px] leading-relaxed text-foreground/90">
        <span className="font-medium text-muted-foreground">Tâche : </span>
        {summary.task || "—"}
      </p>
      <dl className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        <div className="grid gap-0.5">
          <dt className="flex items-center gap-1 text-subtle-foreground">
            <UserRound className="size-3" aria-hidden />
            Créée par
          </dt>
          <dd className="truncate font-medium text-foreground">{summary.created_by_label || "—"}</dd>
        </div>
        <div className="grid gap-0.5">
          <dt className="flex items-center gap-1 text-subtle-foreground">
            <Coins className="size-3" aria-hidden />
            Tokens
          </dt>
          <dd className="font-medium tabular-nums text-foreground">{formatTokens(summary.token_count)}</dd>
        </div>
        <div className="grid gap-0.5">
          <dt className="flex items-center gap-1 text-subtle-foreground">
            <Layers className="size-3" aria-hidden />
            Éléments
          </dt>
          <dd className="font-medium tabular-nums text-foreground">
            {formatNumber(snapshot?.items.length ?? summary.items_count, 0)}
          </dd>
        </div>
        <div className="grid gap-0.5">
          <dt className="flex items-center gap-1 text-subtle-foreground">
            <Fingerprint className="size-3" aria-hidden />
            Empreinte
          </dt>
          <dd className="truncate font-mono font-medium text-foreground" title={summary.content_hash}>
            {shortHash(summary.content_hash, 12)}
          </dd>
        </div>
      </dl>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="grid gap-4" aria-busy="true" aria-label="Chargement de la version">
      <Skeleton className="h-36 rounded-xl" />
      <Skeleton className="h-9 w-64" />
      <div className="grid gap-3 rounded-xl border border-border bg-card p-5">
        <Skeleton className="h-5 w-48" />
        <SkeletonText lines={5} />
        <Skeleton className="h-5 w-40" />
        <SkeletonText lines={4} />
      </div>
    </div>
  );
}

/** /snapshots/[name]: version timeline, content with citations, items table, compare mode. */
export function SnapshotDetailView() {
  const { slug } = useCurrentProject();
  const params = useParams<{ name: string }>();
  const name = typeof params.name === "string" ? safeDecode(params.name) : "";
  const [state, update] = useSnapshotUrlState();
  const [highlight, setHighlight] = React.useState<string | null>(null);

  const versionsQuery = useSnapshotVersions(slug, name);
  const versions = React.useMemo(() => sortVersionsDesc(versionsQuery.data ?? []), [versionsQuery.data]);
  const latest = versions[0]?.version ?? null;
  const selected =
    state.version !== null && versions.some((v) => v.version === state.version) ? state.version : latest;
  const summary = versions.find((v) => v.version === selected);
  const snapshot = useSnapshot(slug, name, selected ?? "latest", { enabled: Boolean(slug && name && selected !== null) });

  const canCompare = versions.length >= 2;
  const mode: Mode = state.mode === "compare" && canCompare ? "compare" : "view";
  const compareTo = state.to && versions.some((v) => v.version === state.to) ? state.to : (selected ?? latest ?? 1);
  const compareFrom =
    state.from && versions.some((v) => v.version === state.from)
      ? state.from
      : (versions.find((v) => v.version < compareTo)?.version ?? versions[versions.length - 1]?.version ?? compareTo);

  const forgottenCount = snapshot.data?.items.filter((i) => i.forgotten).length ?? 0;

  const onCitationClick = React.useCallback(
    (citation: string) => {
      setHighlight(citation);
      update({ tab: "items" });
    },
    [update],
  );

  const backLink = (
    <Button asChild variant="ghost" size="sm" className="-ml-2 w-fit">
      <Link href={`/projects/${encodeURIComponent(slug)}/snapshots`}>
        <ArrowLeft aria-hidden />
        Tous les snapshots
      </Link>
    </Button>
  );

  if (versionsQuery.isError) {
    const notFound = versionsQuery.error.isNotFound;
    return (
      <div className="grid gap-4">
        {backLink}
        <ErrorState
          size="lg"
          error={versionsQuery.error}
          title={notFound ? "Snapshot introuvable" : undefined}
          onRetry={notFound ? undefined : () => void versionsQuery.refetch()}
        />
      </div>
    );
  }

  const versionOptions = versions.map((v) => ({
    value: String(v.version),
    label: `Version ${v.version}${v.version === latest ? " (dernière)" : ""}`,
    description: `${formatDate(v.created_at)} · ${v.created_by_label || "—"}`,
  }));

  return (
    <div className="grid grid-cols-1 gap-5">
      <div className="grid gap-1">
        {backLink}
        <PageHeader
          icon={<Camera />}
          eyebrow="Snapshot de contexte"
          title={<span className="font-mono">{name}</span>}
          meta={
            versionsQuery.isPending ? (
              <Skeleton className="h-6 w-28" />
            ) : (
              <>
                {latest ? (
                  <Badge tone="teal" size="md" mono>
                    v{latest}
                  </Badge>
                ) : null}
                <Badge tone="neutral" size="md" variant="outline">
                  {plural(versions.length, "version")}
                </Badge>
              </>
            )
          }
          description="Contexte partagé, versionné et immuable : chaque version fige le Markdown servi et les éléments cités, réutilisables par un autre agent."
          actions={
            <>
              <SegmentedControl<Mode>
                value={mode}
                onValueChange={(m) => update({ mode: m === "compare" ? "compare" : null })}
                aria-label="Mode"
                options={[
                  { value: "view", label: "Contenu", icon: <FileText aria-hidden /> },
                  { value: "compare", label: "Comparer", icon: <GitCompareArrows aria-hidden />, disabled: !canCompare },
                ]}
              />
              <CopyContentButton content={snapshot.data?.content} />
              {selected ? (
                <Button asChild>
                  <Link href={explorerBaseHref(slug, name, selected)}>
                    <Rocket aria-hidden />
                    Utiliser comme base
                  </Link>
                </Button>
              ) : null}
            </>
          }
          className="pb-0"
        />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[20rem_minmax(0,1fr)] lg:items-start">
        <aside className="hidden lg:sticky lg:top-[4.5rem] lg:block lg:max-h-[calc(100dvh-5.5rem)] lg:overflow-y-auto lg:pr-1">
          <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-subtle-foreground">
            Historique des versions
          </h2>
          {versionsQuery.isPending ? (
            <SnapshotVersionTimelineSkeleton />
          ) : (
            <SnapshotVersionTimeline
              versions={versions}
              selected={selected}
              latest={latest}
              compare={mode === "compare" ? { from: compareFrom, to: compareTo } : null}
              onSelect={(v) => {
                if (mode === "compare") {
                  // In compare mode a click sets the target version (and keeps an older base).
                  const from = v === compareFrom ? compareTo : compareFrom;
                  update({ to: v, from });
                } else {
                  setHighlight(null);
                  update({ v: v === latest ? null : v });
                }
              }}
            />
          )}
        </aside>

        <section className="grid min-w-0 gap-4" aria-label="Version sélectionnée">
          {mode === "view" && versions.length > 1 ? (
            <SimpleSelect
              value={selected ? String(selected) : undefined}
              onValueChange={(v) => update({ v: Number(v) === latest ? null : v })}
              options={versionOptions}
              className="lg:hidden"
              aria-label="Version"
            />
          ) : null}

          {versionsQuery.isPending ? (
            <DetailSkeleton />
          ) : versions.length === 0 ? (
            <EmptyState icon={<Camera />} title="Aucune version" description="Ce snapshot ne contient encore aucune version." />
          ) : mode === "compare" ? (
            <SnapshotDiffView
              slug={slug}
              name={name}
              versions={versions}
              from={compareFrom}
              to={compareTo}
              onChange={(from, to) => update({ mode: "compare", from, to })}
            />
          ) : (
            <>
              {summary ? <VersionSummaryCard summary={summary} snapshot={snapshot.data} /> : null}
              {forgottenCount > 0 ? (
                <Alert tone="amber" title={`${plural(forgottenCount, "élément oublié", "éléments oubliés")} depuis cette version`}>
                  Ils sont masqués à l&apos;affichage et seront exclus (motif « oubli sélectif ») si ce snapshot sert de base à
                  un nouveau contexte.
                </Alert>
              ) : null}
              {snapshot.isPending ? (
                <DetailSkeleton />
              ) : snapshot.isError ? (
                <ErrorState error={snapshot.error} onRetry={() => void snapshot.refetch()} />
              ) : (
                <Tabs value={state.tab} onValueChange={(t) => update({ tab: t === "items" ? "items" : null })}>
                  <TabsList>
                    <TabsTrigger value="content">
                      <FileText aria-hidden />
                      Contenu
                    </TabsTrigger>
                    <TabsTrigger value="items" count={snapshot.data.items.length}>
                      <Layers aria-hidden />
                      Éléments
                    </TabsTrigger>
                  </TabsList>
                  <TabsContent value="content">
                    <article className="rounded-xl border border-border bg-card p-5 shadow-xs sm:p-6">
                      {snapshot.data.content.trim() ? (
                        <SnapshotMarkdown
                          content={snapshot.data.content}
                          items={snapshot.data.items}
                          onCitationClick={onCitationClick}
                        />
                      ) : (
                        <p className="text-[13px] italic text-muted-foreground">Cette version ne contient aucun texte.</p>
                      )}
                    </article>
                  </TabsContent>
                  <TabsContent value="items">
                    <SnapshotItemsTable slug={slug} items={snapshot.data.items} highlight={highlight} />
                  </TabsContent>
                </Tabs>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
