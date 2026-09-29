"use client";

import * as React from "react";
import {
  CalendarClock,
  CornerDownRight,
  CornerLeftUp,
  EyeOff,
  GitBranch,
  History,
  Link2,
  Network,
  Swords,
  Timer,
  X,
} from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { ClassificationBanner } from "@/components/domain/classification-banner";
import { MemoryKindBadge } from "@/components/domain/memory-kind-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { ScopeBadge } from "@/components/domain/scope-badge";
import { ScoreBar } from "@/components/domain/score-bar";
import { StatusBadge } from "@/components/domain/status-badge";
import { AclChips } from "@/components/sources/acl-chips";
import { MarkdownPreview } from "@/components/sources/markdown-preview";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMemory } from "@/lib/api/hooks";
import type { Member, MemoryDetail as MemoryDetailData, MemoryItem } from "@/lib/api/types";
import { getMeta, MEMORY_STATUS_META } from "@/lib/enums";
import { formatDate, formatDateTime, formatPercent, shortId, truncate } from "@/lib/format";
import { cn } from "@/lib/utils";

import { MemoryActions } from "./memory-actions";
import { MemoryActor } from "./memory-actor";
import { HistoryTimeline, ProvenanceList, RelationsList, VersionsList } from "./memory-detail-tabs";
import {
  isExpired,
  supersededByRelation,
  supersedesRelation,
  validityLabel,
  type MemoryPermissions,
} from "./memory-utils";

type DetailTab = "provenance" | "history" | "versions" | "relations";

export interface MemoryDetailProps {
  slug: string;
  itemId: string;
  permissions: MemoryPermissions;
  members?: readonly Member[];
  /** Graph labels (id → title), used to name the superseding item without an extra request. */
  labels?: ReadonlyMap<string, string>;
  onOpenItem: (id: string) => void;
  onClose?: () => void;
  className?: string;
}

function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid min-w-0 gap-1">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-subtle-foreground">{label}</dt>
      <dd className="flex min-w-0 flex-wrap items-center gap-1.5 text-[13px] text-foreground">{children}</dd>
    </div>
  );
}

function LinkButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="font-semibold text-primary underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {children}
    </button>
  );
}

export function MemoryDetailSkeleton() {
  return (
    <div className="grid gap-5 p-5" aria-busy="true" aria-label="Chargement de l'élément mémoire">
      <div className="flex gap-1.5">
        <Skeleton className="h-5 w-20" />
        <Skeleton className="h-5 w-16" />
        <Skeleton className="h-5 w-16" />
      </div>
      <Skeleton className="h-6 w-4/5" />
      <SkeletonText lines={4} />
      <div className="grid grid-cols-2 gap-4">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="grid gap-1.5">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-4 w-28" />
          </div>
        ))}
      </div>
      <Skeleton className="h-9 w-full" />
      <Skeleton className="h-32 w-full" />
    </div>
  );
}

function SupersededCallout({
  slug,
  item,
  data,
  labels,
  onOpenItem,
}: {
  slug: string;
  item: MemoryItem;
  data: MemoryDetailData;
  labels?: ReadonlyMap<string, string>;
  onOpenItem: (id: string) => void;
}) {
  const relation = supersededByRelation(data.relations);
  const targetId = relation?.other_id ?? item.superseded_by_id;
  const knownTitle = relation?.other_title ?? (targetId ? labels?.get(targetId) : undefined);
  const fetched = useMemory(slug, !knownTitle && targetId ? targetId : undefined, { staleTime: 60_000 });
  const title = knownTitle ?? fetched.data?.item.title;
  if (!targetId) return null;
  return (
    <Alert tone="amber" icon={<CornerDownRight aria-hidden />} title="Élément remplacé">
      Remplacé par{" "}
      <LinkButton onClick={() => onOpenItem(targetId)}>{title ? `« ${truncate(title, 90)} »` : "une version plus récente"}</LinkButton>
      . Il n&apos;est plus servi aux agents (exclusion motivée « remplacé »).
      {relation?.detail ? <span className="mt-1 block text-xs opacity-80">{relation.detail}</span> : null}
    </Alert>
  );
}

/** Detail panel of a memory item: content, metadata, lifecycle actions and the provenance/history/versions/relations tabs. */
export function MemoryDetail({ slug, itemId, permissions, members, labels, onOpenItem, onClose, className }: MemoryDetailProps) {
  const query = useMemory(slug, itemId);
  const [tab, setTab] = React.useState<DetailTab>("provenance");

  if (query.isPending) return <MemoryDetailSkeleton />;
  if (query.isError) {
    return (
      <div className="p-5">
        <ErrorState
          error={query.error}
          title={query.error.isNotFound ? "Élément introuvable ou inaccessible" : undefined}
          onRetry={() => void query.refetch()}
          action={
            onClose ? (
              <Button size="sm" variant="ghost" onClick={onClose}>
                Fermer
              </Button>
            ) : undefined
          }
        />
      </div>
    );
  }

  const data = query.data;
  const item = data.item;
  const forgotten = item.status === "forgotten";
  const superseded = item.status === "superseded";
  const current = data.versions.find((v) => v.is_current);
  const replaces = supersedesRelation(data.relations);
  const conflicts = data.relations.filter((r) => r.rel_type === "contradicts");
  const subject = item.subject_user_id ? members?.find((m) => m.user.id === item.subject_user_id) : undefined;
  const expired = isExpired(item);

  return (
    <article className={cn("grid gap-5", className)} aria-labelledby="memory-detail-title">
      <header className="grid gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <MemoryKindBadge kind={item.kind} size="md" />
            <ScopeBadge scope={item.scope} size="md" />
            <StatusBadge kind="memory" status={item.status} size="md" />
            <ClassificationBadge level={item.classification} size="md" />
            <Badge tone={item.is_current ? "teal" : "neutral"} variant="outline" size="md" icon={<GitBranch aria-hidden />}>
              v{item.version}
            </Badge>
          </div>
          {onClose ? (
            <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Fermer le détail" className="-mr-1 -mt-1 shrink-0">
              <X aria-hidden />
            </Button>
          ) : null}
        </div>
        <h2
          id="memory-detail-title"
          className={cn(
            "text-lg font-semibold leading-snug tracking-tight text-foreground",
            superseded && "text-muted-foreground line-through decoration-muted-foreground/60",
          )}
        >
          {item.title}
        </h2>

        {!item.is_current ? (
          <Alert tone="neutral" icon={<History aria-hidden />} title={`Version antérieure (v${item.version})`}>
            Vous consultez une version archivée.{" "}
            {current ? <LinkButton onClick={() => onOpenItem(current.id)}>Voir la version courante (v{current.version})</LinkButton> : null}
          </Alert>
        ) : null}
        {superseded ? <SupersededCallout slug={slug} item={item} data={data} labels={labels} onOpenItem={onOpenItem} /> : null}
        {replaces ? (
          <p className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
            <CornerLeftUp className="size-4 shrink-0" aria-hidden />
            <span className="min-w-0">
              Remplace{" "}
              <LinkButton onClick={() => onOpenItem(replaces.other_id)}>
                « {truncate(replaces.other_title || "élément précédent", 80)} »
              </LinkButton>
            </span>
          </p>
        ) : null}
        {conflicts.length > 0 && !forgotten ? (
          <Alert tone="amber" icon={<Swords aria-hidden />} title="Contradiction détectée">
            En contradiction avec{" "}
            {conflicts.map((c, i) => (
              <React.Fragment key={c.id}>
                {i > 0 ? ", " : null}
                {c.other_type === "memory" ? (
                  <LinkButton onClick={() => onOpenItem(c.other_id)}>« {truncate(c.other_title || "un autre élément", 60)} »</LinkButton>
                ) : (
                  <span className="font-medium">« {truncate(c.other_title || "une source", 60)} »</span>
                )}
              </React.Fragment>
            ))}
            . À l&apos;assemblage, la source la plus fiable l&apos;emporte (validé, puis plus récent, puis confiance).
          </Alert>
        ) : null}
        <ClassificationBanner level={item.classification} context="display" compact />

        <MemoryActions slug={slug} item={item} permissions={permissions} onItemChanged={onOpenItem} />
      </header>

      <section aria-label="Contenu" className="rounded-xl border border-border bg-card p-4">
        {forgotten ? (
          <div className="flex items-start gap-3 text-[13px] text-muted-foreground">
            <EyeOff className="mt-0.5 size-4 shrink-0" aria-hidden />
            <p>
              Contenu effacé par oubli sélectif. Seuls le titre et les métadonnées sont conservés pour l&apos;audit ; cet
              élément n&apos;est plus jamais servi aux agents.
            </p>
          </div>
        ) : (
          <MarkdownPreview content={item.content} />
        )}
      </section>

      <dl className="grid grid-cols-1 gap-x-6 gap-y-4 rounded-xl border border-border bg-muted/20 p-4 sm:grid-cols-2">
        <MetaRow label="Statut">
          <StatusBadge kind="memory" status={item.status} />
          <span className="text-xs text-muted-foreground">{getMeta(MEMORY_STATUS_META, item.status).description}</span>
        </MetaRow>
        <MetaRow label="Confiance">
          <ScoreBar value={item.confidence} widthClassName="w-24" />
          <span className="text-xs text-muted-foreground">{formatPercent(item.confidence)}</span>
        </MetaRow>
        <MetaRow label="Validité">
          <CalendarClock className="size-3.5 text-muted-foreground" aria-hidden />
          <span>{validityLabel(item)}</span>
          {expired ? (
            <Badge tone="amber" dot>
              Échue
            </Badge>
          ) : null}
        </MetaRow>
        <MetaRow label="Créé par">
          <MemoryActor type={item.created_by_type} id={item.created_by_id} label={item.created_by_label} members={members} size="xs" />
          <span className="text-xs text-muted-foreground" title={formatDateTime(item.created_at)}>
            le {formatDate(item.created_at)}
          </span>
        </MetaRow>
        <MetaRow label="Version">
          <span className="font-medium">v{item.version}</span>
          <span className="text-xs text-muted-foreground">
            sur {data.versions.length || 1} · lignée <span className="font-mono">{shortId(item.lineage_id)}</span>
          </span>
        </MetaRow>
        <MetaRow label="Mis à jour">
          <RelativeTime date={item.updated_at} />
        </MetaRow>
        <MetaRow label="Accès">
          <AclChips principals={item.acl_principals} members={members} max={3} />
        </MetaRow>
        <MetaRow label="Étiquettes">
          {item.tags.length > 0 ? (
            item.tags.map((tag) => (
              <Badge key={tag} variant="outline">
                {tag}
              </Badge>
            ))
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </MetaRow>
        {item.scope === "user" ? (
          <MetaRow label="Personne concernée">
            {subject ? (
              <MemoryActor type="user" id={subject.user.id} label={subject.user.full_name} members={members} size="xs" />
            ) : (
              <span className="text-muted-foreground">Utilisateur {shortId(item.subject_user_id)}</span>
            )}
          </MetaRow>
        ) : null}
        {item.scope === "short_term" ? (
          <MetaRow label="Session">
            <Timer className="size-3.5 text-muted-foreground" aria-hidden />
            <span className="font-mono text-xs">{item.session_id ?? "—"}</span>
            {item.expires_at ? (
              <span className="text-xs text-muted-foreground">
                expire <RelativeTime date={item.expires_at} />
              </span>
            ) : null}
          </MetaRow>
        ) : null}
      </dl>

      <Tabs value={tab} onValueChange={(v) => setTab(v as DetailTab)}>
        <TabsList>
          <TabsTrigger value="provenance" count={data.provenance.length}>
            <Link2 aria-hidden />
            Provenance
          </TabsTrigger>
          <TabsTrigger value="history" count={data.history.length}>
            <History aria-hidden />
            Historique
          </TabsTrigger>
          <TabsTrigger value="versions" count={data.versions.length}>
            <GitBranch aria-hidden />
            Versions
          </TabsTrigger>
          <TabsTrigger value="relations" count={data.relations.length}>
            <Network aria-hidden />
            Relations
          </TabsTrigger>
        </TabsList>
        <TabsContent value="provenance">
          <ProvenanceList slug={slug} provenance={data.provenance} />
        </TabsContent>
        <TabsContent value="history">
          <HistoryTimeline history={data.history} versions={data.versions} members={members} />
        </TabsContent>
        <TabsContent value="versions">
          <VersionsList versions={data.versions} viewedId={item.id} members={members} onOpen={onOpenItem} />
        </TabsContent>
        <TabsContent value="relations">
          <RelationsList slug={slug} relations={data.relations} onOpenItem={onOpenItem} />
        </TabsContent>
      </Tabs>
    </article>
  );
}
