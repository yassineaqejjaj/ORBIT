"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowRight,
  Brain,
  ChevronDown,
  ChevronUp,
  CircleDot,
  ExternalLink,
  FileText,
  History,
  Layers,
  Link2,
  MessageSquareText,
  Network,
  Quote,
  Telescope,
} from "lucide-react";

import { MemoryEventBadge, RelationTypeBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { ScoreBar } from "@/components/domain/score-bar";
import { StatusBadge } from "@/components/domain/status-badge";
import { MarkdownPreview } from "@/components/sources/markdown-preview";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import type { Member, MemoryEvent, MemoryItem, Provenance, Relation } from "@/lib/api/types";
import { getMeta, MEMORY_EVENT_META } from "@/lib/enums";
import { formatDateTime, formatScore, shortId } from "@/lib/format";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

import { MemoryActor } from "./memory-actor";
import { changesForEvent, wordDiff, type FieldChange } from "./memory-utils";

/* -------------------------------------------------------------------------- */
/* Provenance                                                                 */
/* -------------------------------------------------------------------------- */

function Excerpt({ text }: { text: string }) {
  const [expanded, setExpanded] = React.useState(false);
  const long = text.length > 320;
  return (
    <div className="grid gap-1">
      <blockquote
        className={cn(
          "relative rounded-md border-l-2 border-brand/50 bg-muted/50 py-2 pl-3 pr-2 text-[12.5px] leading-relaxed text-foreground/90",
          !expanded && long && "line-clamp-5",
        )}
      >
        {text}
      </blockquote>
      {long ? (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="inline-flex w-fit items-center gap-1 text-xs font-medium text-primary hover:underline"
        >
          {expanded ? <ChevronUp className="size-3.5" aria-hidden /> : <ChevronDown className="size-3.5" aria-hidden />}
          {expanded ? "Réduire" : "Afficher tout l'extrait"}
        </button>
      ) : null}
    </div>
  );
}

export function ProvenanceList({ slug, provenance }: { slug: string; provenance: readonly Provenance[] }) {
  if (provenance.length === 0) {
    return (
      <EmptyState
        size="sm"
        icon={<Link2 />}
        title="Aucune provenance enregistrée"
        description="Cet élément a été saisi manuellement ou proposé par un agent sans source rattachée."
      />
    );
  }
  return (
    <ol className="grid gap-3">
      {provenance.map((p) => (
        <li key={p.id} className="grid gap-2 rounded-lg border border-border bg-card p-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="flex min-w-0 items-start gap-2">
              <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-600/20 dark:bg-blue-400/10 dark:text-blue-300 dark:ring-blue-400/25">
                <FileText className="size-3.5" aria-hidden />
              </span>
              <div className="grid min-w-0 gap-0.5">
                {p.document_id ? (
                  <Link
                    href={`/projects/${encodeURIComponent(slug)}/sources/${encodeURIComponent(p.document_id)}`}
                    className="inline-flex min-w-0 items-center gap-1 text-[13px] font-medium text-foreground hover:text-primary hover:underline"
                  >
                    <span className="truncate">{p.document_title || p.source_label || "Document source"}</span>
                    <ExternalLink className="size-3 shrink-0 opacity-60" aria-hidden />
                  </Link>
                ) : (
                  <span className="truncate text-[13px] font-medium text-foreground">
                    {p.source_label || "Source non documentaire"}
                  </span>
                )}
                <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                  {p.document_id && p.source_label ? <span className="truncate">{p.source_label}</span> : null}
                  {p.chunk_id ? (
                    <span className="inline-flex items-center gap-1 font-mono text-[11px]" title={p.chunk_id}>
                      <Layers className="size-3" aria-hidden />
                      extrait {shortId(p.chunk_id)}
                    </span>
                  ) : null}
                  {p.context_request_id ? (
                    <span className="inline-flex items-center gap-1" title={p.context_request_id}>
                      <Telescope className="size-3" aria-hidden />
                      requête de contexte {shortId(p.context_request_id)}
                    </span>
                  ) : null}
                </span>
              </div>
            </div>
            <RelativeTime date={p.created_at} className="text-xs text-muted-foreground" />
          </div>
          {p.excerpt ? <Excerpt text={p.excerpt} /> : null}
        </li>
      ))}
    </ol>
  );
}

/* -------------------------------------------------------------------------- */
/* History                                                                    */
/* -------------------------------------------------------------------------- */

function InlineWordDiff({ before, after }: { before: string; after: string }) {
  const ops = React.useMemo(() => wordDiff(before, after), [before, after]);
  if (!ops) {
    return (
      <div className="grid gap-2 text-[12.5px]">
        <p className="rounded-md bg-red-50 p-2 text-red-900 line-through decoration-red-400/70 dark:bg-red-400/10 dark:text-red-200">
          {before}
        </p>
        <p className="rounded-md bg-emerald-50 p-2 text-emerald-900 dark:bg-emerald-400/10 dark:text-emerald-200">{after}</p>
      </div>
    );
  }
  return (
    <p className="max-h-60 overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-border bg-background p-2.5 text-[12.5px] leading-relaxed">
      {ops.map((op, i) =>
        op.type === "equal" ? (
          <span key={i}>{op.text}</span>
        ) : op.type === "insert" ? (
          <ins
            key={i}
            className="rounded-sm bg-emerald-100 text-emerald-900 no-underline dark:bg-emerald-400/20 dark:text-emerald-100"
          >
            {op.text}
          </ins>
        ) : (
          <del
            key={i}
            className="rounded-sm bg-red-100 text-red-900 decoration-red-500/70 dark:bg-red-400/20 dark:text-red-200"
          >
            {op.text}
          </del>
        ),
      )}
    </p>
  );
}

function ChangeList({ changes }: { changes: readonly FieldChange[] }) {
  return (
    <div className="grid gap-2 rounded-md border border-border bg-muted/30 p-2.5">
      {changes.map((c) => (
        <div key={c.field} className="grid gap-1">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-subtle-foreground">{c.label}</span>
          {c.long ? (
            <InlineWordDiff before={c.before} after={c.after} />
          ) : (
            <span className="flex flex-wrap items-center gap-1.5 text-[12.5px]">
              <span className="rounded bg-red-50 px-1.5 py-0.5 text-red-800 line-through decoration-red-400/70 dark:bg-red-400/10 dark:text-red-200">
                {c.before}
              </span>
              <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden />
              <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-800 dark:bg-emerald-400/10 dark:text-emerald-200">
                {c.after}
              </span>
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

/** Human details stored in `event.data` for non-edit events (similarity, related title, version). */
function eventFacts(event: MemoryEvent): string[] {
  const data = event.data ?? {};
  const facts: string[] = [];
  const title = data.other_title ?? data.by_title ?? data.superseded_by_title ?? data.supersedes_title;
  if (typeof title === "string" && title) {
    const prefix =
      event.event === "conflict_detected" ? "En contradiction avec" : event.event === "superseded" ? "Remplacé par" : "Lié à";
    facts.push(`${prefix} « ${title} »`);
  }
  const similarity = data.similarity ?? data.score;
  if (typeof similarity === "number") facts.push(`similarité ${formatScore(similarity)}`);
  if (typeof data.version === "number") facts.push(`version ${data.version}`);
  if (typeof data.propagated === "number" && data.propagated > 0) facts.push(`${data.propagated} élément(s) dérivé(s) impacté(s)`);
  return facts;
}

export function HistoryTimeline({
  history,
  versions,
  members,
}: {
  history: readonly MemoryEvent[];
  versions: readonly MemoryItem[];
  members?: readonly Member[];
}) {
  const events = React.useMemo(
    () => [...history].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
    [history],
  );
  if (events.length === 0) {
    return <EmptyState size="sm" icon={<History />} title="Aucun événement" description="L'historique de cet élément est vide." />;
  }
  return (
    <ol className="relative grid gap-0">
      {events.map((event, index) => {
        const meta = getMeta(MEMORY_EVENT_META, event.event);
        const changes = event.event === "edited" ? changesForEvent(event, versions) : [];
        const facts = eventFacts(event);
        const last = index === events.length - 1;
        return (
          <li key={event.id} className="relative grid grid-cols-[1.5rem_minmax(0,1fr)] gap-3 pb-5 last:pb-0">
            {!last ? <span className="absolute bottom-0 left-[11px] top-6 w-px bg-border" aria-hidden /> : null}
            <span
              className={cn(
                "relative z-10 mt-0.5 flex size-6 items-center justify-center rounded-full ring-4 ring-background",
                toneClasses(meta.tone).soft,
              )}
              aria-hidden
            >
              <CircleDot className="size-3" />
            </span>
            <div className="grid min-w-0 gap-1.5">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <MemoryEventBadge value={event.event} />
                <MemoryActor
                  type={event.actor_type}
                  id={event.actor_id}
                  label={event.actor_label}
                  members={members}
                  size="xs"
                />
                <span className="ml-auto text-xs text-muted-foreground" title={formatDateTime(event.created_at)}>
                  <RelativeTime date={event.created_at} />
                </span>
              </div>
              {event.reason ? (
                <p className="flex items-start gap-1.5 text-[12.5px] leading-relaxed text-foreground/90">
                  <Quote className="mt-0.5 size-3.5 shrink-0 text-subtle-foreground" aria-hidden />
                  <span className="italic">{event.reason}</span>
                </p>
              ) : null}
              {facts.length > 0 ? <p className="text-xs text-muted-foreground">{facts.join(" · ")}</p> : null}
              {changes.length > 0 ? <ChangeList changes={changes} /> : null}
              <span className="text-[11px] text-subtle-foreground">{formatDateTime(event.created_at)}</span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/* -------------------------------------------------------------------------- */
/* Versions                                                                   */
/* -------------------------------------------------------------------------- */

export function VersionsList({
  versions,
  viewedId,
  members,
  onOpen,
}: {
  versions: readonly MemoryItem[];
  viewedId: string;
  members?: readonly Member[];
  onOpen: (id: string) => void;
}) {
  const sorted = React.useMemo(() => [...versions].sort((a, b) => b.version - a.version), [versions]);
  const [expanded, setExpanded] = React.useState<string | null>(null);

  if (sorted.length === 0) {
    return <EmptyState size="sm" icon={<History />} title="Aucune version" description="Aucune version n'est disponible." />;
  }
  return (
    <ol className="grid gap-2">
      {sorted.map((v) => {
        const open = expanded === v.id;
        const viewed = v.id === viewedId;
        return (
          <li
            key={v.id}
            className={cn(
              "grid gap-2 rounded-lg border bg-card p-3",
              viewed ? "border-brand/50 ring-1 ring-brand/20" : "border-border",
            )}
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={v.is_current ? "teal" : "neutral"} variant={v.is_current ? "solid" : "outline"} mono>
                v{v.version}
              </Badge>
              {v.is_current ? (
                <Badge tone="teal" dot>
                  Version courante
                </Badge>
              ) : null}
              <StatusBadge kind="memory" status={v.status} />
              {viewed ? <span className="text-xs font-medium text-primary">affichée</span> : null}
              <span className="ml-auto text-xs text-muted-foreground">
                <RelativeTime date={v.created_at} />
              </span>
            </div>
            <p className={cn("text-[13px] font-medium", v.status === "superseded" && "line-through text-muted-foreground")}>
              {v.title}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <MemoryActor
                type={v.created_by_type}
                id={v.created_by_id}
                label={v.created_by_label}
                members={members}
                size="xs"
              />
              <div className="ml-auto flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="xs"
                  onClick={() => setExpanded(open ? null : v.id)}
                  aria-expanded={open}
                  leftIcon={open ? <ChevronUp aria-hidden /> : <ChevronDown aria-hidden />}
                >
                  {open ? "Masquer" : "Voir le contenu"}
                </Button>
                {!viewed ? (
                  <Button variant="ghost" size="xs" onClick={() => onOpen(v.id)} leftIcon={<ExternalLink aria-hidden />}>
                    Ouvrir
                  </Button>
                ) : null}
              </div>
            </div>
            {open ? (
              <div className="rounded-md border border-border bg-muted/30 p-3">
                {v.status === "forgotten" ? (
                  <p className="text-[13px] italic text-muted-foreground">Contenu effacé par oubli sélectif.</p>
                ) : (
                  <MarkdownPreview content={v.content} />
                )}
              </div>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

/* -------------------------------------------------------------------------- */
/* Relations                                                                  */
/* -------------------------------------------------------------------------- */

function NodeChip({ children, self = false }: { children: React.ReactNode; self?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md px-2 py-1 text-xs ring-1 ring-inset",
        self
          ? "bg-brand-soft font-semibold text-foreground ring-brand/30"
          : "bg-background font-medium text-foreground ring-border",
      )}
    >
      {children}
    </span>
  );
}

function OtherNode({
  slug,
  relation,
  onOpenItem,
}: {
  slug: string;
  relation: Relation;
  onOpenItem: (id: string) => void;
}) {
  const title = relation.other_title || (relation.other_type === "chunk" ? "Extrait de source" : "Élément sans titre");
  if (relation.other_type === "memory") {
    return (
      <button
        type="button"
        onClick={() => onOpenItem(relation.other_id)}
        className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md bg-background px-2 py-1 text-xs font-medium text-primary ring-1 ring-inset ring-border hover:bg-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Brain className="size-3.5 shrink-0" aria-hidden />
        <span className="truncate">{title}</span>
      </button>
    );
  }
  if (relation.other_type === "document") {
    return (
      <Link
        href={`/projects/${encodeURIComponent(slug)}/sources/${encodeURIComponent(relation.other_id)}`}
        className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md bg-background px-2 py-1 text-xs font-medium text-primary ring-1 ring-inset ring-border hover:bg-accent hover:underline"
      >
        <FileText className="size-3.5 shrink-0" aria-hidden />
        <span className="truncate">{title}</span>
      </Link>
    );
  }
  return (
    <NodeChip>
      <Layers className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      <span className="truncate">{title}</span>
    </NodeChip>
  );
}

export function RelationsList({
  slug,
  relations,
  onOpenItem,
}: {
  slug: string;
  relations: readonly Relation[];
  onOpenItem: (id: string) => void;
}) {
  if (relations.length === 0) {
    return (
      <EmptyState
        size="sm"
        icon={<Network />}
        title="Aucune relation"
        description="Aucun remplacement, contradiction ni dérivation n'a été détecté pour cet élément."
      />
    );
  }
  return (
    <ul className="grid gap-2">
      {relations.map((r) => {
        const self = (
          <NodeChip self>
            <CircleDot className="size-3.5 shrink-0 text-brand" aria-hidden />
            Cet élément
          </NodeChip>
        );
        const other = <OtherNode slug={slug} relation={r} onOpenItem={onOpenItem} />;
        const arrow = (
          <span className="inline-flex shrink-0 items-center gap-1">
            <span className="h-px w-3 bg-border-strong" aria-hidden />
            <RelationTypeBadge value={r.rel_type} />
            <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden />
          </span>
        );
        return (
          <li key={r.id} className="grid gap-2 rounded-lg border border-border bg-card p-3">
            <div className="flex flex-wrap items-center gap-1.5">
              {r.direction === "out" ? (
                <>
                  {self}
                  {arrow}
                  {other}
                </>
              ) : (
                <>
                  {other}
                  {arrow}
                  {self}
                </>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                Confiance <ScoreBar value={r.confidence} widthClassName="w-12" />
              </span>
              {r.detail ? (
                <span className="inline-flex min-w-0 items-center gap-1">
                  <MessageSquareText className="size-3.5 shrink-0" aria-hidden />
                  <span className="truncate" title={r.detail}>
                    {r.detail}
                  </span>
                </span>
              ) : null}
              <RelativeTime date={r.created_at} className="ml-auto" />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
