"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, History, RefreshCw, ScrollText } from "lucide-react";

import { ActorAvatar } from "@/components/overview/actor-avatar";
import { auditTargetHref } from "@/components/overview/activity-timeline";
import { AUDIT_ACTION_META, AUDIT_DOMAINS, auditActionMeta, auditTargetLabel } from "@/components/overview/audit-meta";
import { parsePositiveInt, useUrlParams } from "@/components/sources/use-url-params";
import { RelativeTime } from "@/components/domain/relative-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { JsonViewer } from "@/components/ui/json-viewer";
import { Pagination } from "@/components/ui/pagination";
import { SimpleSelect, type SimpleSelectOption } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCurrentProject } from "@/hooks/use-current-project";
import { useAudit, useMembers } from "@/lib/api/hooks";
import type { AuditEvent, Member } from "@/lib/api/types";
import { ACTOR_TYPE_META, type ActorType } from "@/lib/enums";
import { formatDateTimePrecise, plural, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

/** API default page size (`Page<T>`), used until the first page is loaded. */
const DEFAULT_PAGE_SIZE = 25;
const ALL = "__all__";
const COLUMNS = 5;

const DOMAIN_OPTIONS: SimpleSelectOption[] = [
  { value: ALL, label: "Toutes les actions" },
  ...AUDIT_DOMAINS.map((d) => ({ value: d.value, label: d.label })),
];

function verbOptions(domain: string): SimpleSelectOption[] {
  const actions = Object.entries(AUDIT_ACTION_META).filter(([action]) => action.startsWith(`${domain}.`));
  return [{ value: ALL, label: "Toutes les opérations" }, ...actions.map(([value, meta]) => ({ value, label: meta.label }))];
}

function isActorType(value: string): value is ActorType {
  return value in ACTOR_TYPE_META;
}

function hasDetails(event: AuditEvent): boolean {
  return Boolean(event.details) && Object.keys(event.details).length > 0;
}

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 6 }, (_, i) => (
        <TableRow key={i}>
          <TableCell>
            <Skeleton className="h-4 w-32" />
          </TableCell>
          <TableCell>
            <div className="flex items-center gap-2">
              <Skeleton className="size-6 rounded-full" />
              <Skeleton className="h-4 w-28" />
            </div>
          </TableCell>
          <TableCell>
            <Skeleton className="h-5 w-28 rounded-md" />
          </TableCell>
          <TableCell>
            <Skeleton className="h-4 w-24" />
          </TableCell>
          <TableCell>
            <Skeleton className="h-4 w-64" />
          </TableCell>
        </TableRow>
      ))}
    </>
  );
}

interface AuditRowProps {
  slug: string;
  event: AuditEvent;
  members: readonly Member[];
  expanded: boolean;
  onToggle: () => void;
}

function AuditRow({ slug, event, members, expanded, onToggle }: AuditRowProps) {
  const meta = auditActionMeta(event.action);
  const href = auditTargetHref(slug, event);
  const expandable = hasDetails(event);
  const detailsId = `audit-details-${event.id}`;
  const actorTypeLabel = isActorType(event.actor_type) ? ACTOR_TYPE_META[event.actor_type].label : event.actor_type;

  return (
    <>
      <TableRow className={cn(expanded && "border-b-0 bg-muted/30")}>
        <TableCell className="whitespace-nowrap align-top">
          <div className="grid gap-0.5">
            <span className="font-mono text-xs tabular-nums text-foreground">{formatDateTimePrecise(event.created_at)}</span>
            <RelativeTime date={event.created_at} className="text-[11.5px] text-subtle-foreground" />
          </div>
        </TableCell>
        <TableCell className="align-top">
          <div className="flex min-w-0 items-center gap-2">
            <ActorAvatar actorType={event.actor_type} actorId={event.actor_id} label={event.actor_label} members={members} size="sm" />
            <div className="grid min-w-0">
              <span className="truncate text-[13px] font-medium text-foreground">{event.actor_label || "—"}</span>
              <span className="text-[11.5px] text-subtle-foreground">{actorTypeLabel}</span>
            </div>
          </div>
        </TableCell>
        <TableCell className="align-top">
          <div className="grid justify-items-start gap-1">
            <Badge tone={meta.tone} size="sm">
              {meta.label}
            </Badge>
            <span className="font-mono text-[11px] text-subtle-foreground">{event.action}</span>
          </div>
        </TableCell>
        <TableCell className="align-top">
          <div className="grid gap-0.5">
            <span className="text-[13px] text-foreground">{auditTargetLabel(event.target_type)}</span>
            {event.target_id ? (
              href ? (
                <Link
                  href={href}
                  className="font-mono text-[11px] text-primary underline-offset-4 hover:underline"
                  title={event.target_id}
                >
                  {displayTargetId(event.target_id)}
                </Link>
              ) : (
                <span className="font-mono text-[11px] text-subtle-foreground" title={event.target_id}>
                  {displayTargetId(event.target_id)}
                </span>
              )
            ) : null}
          </div>
        </TableCell>
        <TableCell className="align-top">
          <div className="flex items-start justify-between gap-2">
            <p className="min-w-0 text-[13px] leading-relaxed text-muted-foreground">{event.summary || "—"}</p>
            {expandable ? (
              <Button
                variant="ghost"
                size="xs"
                onClick={onToggle}
                aria-expanded={expanded}
                aria-controls={detailsId}
                className="shrink-0"
              >
                {expanded ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
                Détails
              </Button>
            ) : null}
          </div>
        </TableCell>
      </TableRow>
      {expanded && expandable ? (
        <TableRow id={detailsId} className="bg-muted/30 hover:bg-muted/30">
          <TableCell colSpan={COLUMNS} className="pt-0">
            <JsonViewer data={event.details} rootLabel="details" defaultExpandDepth={2} maxHeightClassName="max-h-72" />
          </TableCell>
        </TableRow>
      ) : null}
    </>
  );
}

/** "Audit" tab: paginated, filterable journal of every significant action on the project (read-only). */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** UUIDs are shortened; readable identifiers (e.g. "spec-atlas@v2") are shown as-is. */
function displayTargetId(id: string): string {
  return UUID_RE.test(id) ? shortId(id) : id;
}

export function AuditPanel() {
  const { slug } = useCurrentProject();
  const { get, set } = useUrlParams();
  const members = useMembers(slug);

  const actionParam = get("action") ?? "";
  const page = parsePositiveInt(get("page"));
  const [domain = "", verb = ""] = actionParam.split(".");
  const domainValue = AUDIT_DOMAINS.some((d) => d.value === domain) ? domain : ALL;
  const verbValue = domainValue !== ALL && verb && `${domain}.${verb}` in AUDIT_ACTION_META ? `${domain}.${verb}` : ALL;
  const action = domainValue === ALL ? undefined : verbValue === ALL ? domainValue : verbValue;

  const audit = useAudit(slug, { action, page });
  const [expanded, setExpanded] = React.useState<ReadonlySet<string>>(() => new Set());

  const events = audit.data?.items ?? [];
  const total = audit.data?.total ?? 0;
  const pageSize = audit.data?.page_size ?? DEFAULT_PAGE_SIZE;
  const lastPage = Math.max(1, Math.ceil(total / pageSize));

  // A filter change can leave the URL on a page that no longer exists.
  React.useEffect(() => {
    if (audit.data && total > 0 && page > lastPage) set({ page: lastPage === 1 ? null : lastPage });
  }, [audit.data, total, page, lastPage, set]);

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const changeDomain = (value: string) => set({ action: value === ALL ? null : value, page: null });
  const changeVerb = (value: string) => set({ action: value === ALL ? domainValue : value, page: null });
  const filtered = action !== undefined;

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <SimpleSelect
            value={domainValue}
            onValueChange={changeDomain}
            options={DOMAIN_OPTIONS}
            size="sm"
            className="w-60"
            aria-label="Filtrer par domaine d'action"
          />
          {domainValue !== ALL ? (
            <SimpleSelect
              value={verbValue}
              onValueChange={changeVerb}
              options={verbOptions(domainValue)}
              size="sm"
              className="w-56"
              aria-label="Filtrer par opération"
            />
          ) : null}
          {filtered ? (
            <Button variant="ghost" size="sm" onClick={() => set({ action: null, page: null })}>
              Réinitialiser
            </Button>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {audit.data ? plural(total, "événement") : audit.isPending ? "Chargement du journal…" : null}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void audit.refetch()}
            disabled={audit.isFetching}
            aria-label="Actualiser le journal d'audit"
          >
            <RefreshCw className={cn(audit.isFetching && "animate-spin")} aria-hidden />
            Actualiser
          </Button>
        </div>
      </div>

      {audit.isError && !audit.data ? (
        <ErrorState error={audit.error} title="Impossible de charger le journal d'audit" onRetry={() => void audit.refetch()} />
      ) : (
        <Card className="overflow-hidden">
          {!audit.isPending && events.length === 0 ? (
            <EmptyState
              variant="plain"
              icon={filtered ? <History /> : <ScrollText />}
              title={filtered ? "Aucun événement pour ce filtre" : "Aucun événement enregistré"}
              description={
                filtered
                  ? "Aucune action de ce type n'a été journalisée sur ce projet. Essayez un autre domaine."
                  : "Les connexions, ingestions, décisions de mémoire, contextes servis et changements de droits apparaîtront ici."
              }
              action={
                filtered ? (
                  <Button variant="outline" size="sm" onClick={() => set({ action: null, page: null })}>
                    Afficher toutes les actions
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <Table aria-busy={audit.isFetching}>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-44">Date</TableHead>
                  <TableHead className="w-52">Acteur</TableHead>
                  <TableHead className="w-52">Action</TableHead>
                  <TableHead className="w-32">Cible</TableHead>
                  <TableHead>Résumé</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody className={cn(audit.isPlaceholderData && "opacity-60 transition-opacity")}>
                {audit.isPending ? (
                  <SkeletonRows />
                ) : (
                  events.map((event) => (
                    <AuditRow
                      key={event.id}
                      slug={slug}
                      event={event}
                      members={members.data ?? []}
                      expanded={expanded.has(event.id)}
                      onToggle={() => toggle(event.id)}
                    />
                  ))
                )}
              </TableBody>
            </Table>
          )}
          {total > pageSize ? (
            <div className="border-t border-border px-4 py-3">
              <Pagination
                page={Math.min(page, lastPage)}
                pageSize={pageSize}
                total={total}
                onPageChange={(next) => set({ page: next === 1 ? null : next })}
                disabled={audit.isFetching}
              />
            </div>
          ) : null}
        </Card>
      )}

      <p className="text-[11.5px] text-subtle-foreground">
        Journal immuable : chaque action significative (connexion, ingestion, oubli, décision de mémoire, contexte servi, agent,
        droits et classification) est horodatée avec son auteur.
      </p>
    </div>
  );
}
