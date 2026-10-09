"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowUpRight, Camera, ListTree } from "lucide-react";

import { EnumIcon } from "@/components/domain/enum-icon";
import { TokenMeter } from "@/components/domain/token-meter";
import { StarRating } from "@/components/explorer/star-rating";
import { Badge } from "@/components/ui/badge";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { Pagination } from "@/components/ui/pagination";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { Table, TableBody, TableCell, TableEmptyRow, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAgents, useContextRequests } from "@/lib/api/hooks";
import type { ContextRequestSummary } from "@/lib/api/types";
import { AGENT_KIND_META } from "@/lib/enums";
import { formatDateTime, formatMs, formatNumber, truncate } from "@/lib/format";
import { LiveIndicator } from "@/components/layout/live-indicator";
import { useFreshIds, useLivePollInterval } from "@/lib/live/live-events";
import { cn } from "@/lib/utils";

const ALL = "all";
const COLUMNS = 9;

function explorerHref(slug: string, id: string): string {
  return `/projects/${encodeURIComponent(slug)}/explorer?request=${encodeURIComponent(id)}`;
}

function LogRow({ request, slug, fresh }: { request: ContextRequestSummary; slug: string; fresh?: boolean }) {
  const router = useRouter();
  const href = explorerHref(slug, request.id);
  return (
    <TableRow
      interactive
      onClick={(e) => {
        // The task cell holds a real link (keyboard / middle-click); the rest of the row is a mouse shortcut.
        if ((e.target as HTMLElement).closest("a, button")) return;
        router.push(href);
      }}
      className={cn("group", fresh && "live-flash")}
    >
      <TableCell className="whitespace-nowrap tabular-nums text-muted-foreground">{formatDateTime(request.created_at)}</TableCell>
      <TableCell className="max-w-[22rem]">
        <SimpleTooltip content={request.task.length > 80 ? request.task : undefined}>
          <Link
            href={href}
            className="flex items-center gap-1.5 rounded-sm font-medium text-foreground hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={`Ouvrir dans l'explorateur : ${request.task}`}
          >
            <span className="truncate">{truncate(request.task, 80)}</span>
            <ArrowUpRight className="size-3.5 shrink-0 text-subtle-foreground opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
          </Link>
        </SimpleTooltip>
      </TableCell>
      <TableCell className="whitespace-nowrap">
        {request.agent ? (
          <span className="inline-flex items-center gap-1.5">
            <EnumIcon name={AGENT_KIND_META[request.agent.kind]?.icon} className="size-3.5 text-muted-foreground" />
            {request.agent.name}
          </span>
        ) : (
          <span className="text-subtle-foreground">Humain</span>
        )}
      </TableCell>
      <TableCell className="whitespace-nowrap text-muted-foreground">{request.user?.full_name ?? "—"}</TableCell>
      <TableCell className={cn("whitespace-nowrap text-right tabular-nums", request.latency_ms > 1500 && "text-amber-700 dark:text-amber-300")}>
        {formatMs(request.latency_ms)}
      </TableCell>
      <TableCell className="min-w-36">
        <TokenMeter used={request.tokens_used} budget={request.token_budget} />
      </TableCell>
      <TableCell className="whitespace-nowrap text-right tabular-nums">
        <span className="font-medium text-primary">{formatNumber(request.included_count, 0)}</span>
        <span className="text-subtle-foreground"> / </span>
        <span className="text-muted-foreground">{formatNumber(request.excluded_count, 0)}</span>
      </TableCell>
      <TableCell className="whitespace-nowrap">
        {request.snapshot ? (
          <Badge tone="violet" icon={<Camera aria-hidden />}>
            {request.snapshot.name} · v{request.snapshot.version}
          </Badge>
        ) : (
          <span className="text-subtle-foreground">—</span>
        )}
      </TableCell>
      <TableCell className="whitespace-nowrap">
        {typeof request.rating === "number" ? <StarRating value={request.rating} /> : <span className="text-subtle-foreground">—</span>}
      </TableCell>
    </TableRow>
  );
}

/** Paginated log of context requests; a row opens the stored request in the explorer. */
export function RequestLog({ slug }: { slug: string }) {
  const [page, setPage] = React.useState(1);
  const [agent, setAgent] = React.useState<string>(ALL);
  const agents = useAgents(slug);
  const poll = useLivePollInterval();
  const requests = useContextRequests(
    slug,
    { page, ...(agent !== ALL ? { agent_id: agent } : {}) },
    { refetchInterval: poll },
  );
  const fresh = useFreshIds(
    (requests.data?.items ?? []).map((r) => r.id),
    `${page}:${agent}`,
  );

  const options = React.useMemo(
    () => [{ value: ALL, label: "Tous les demandeurs" }, ...(agents.data ?? []).map((a) => ({ value: a.id, label: a.name }))],
    [agents.data],
  );

  return (
    <Card className="min-w-0">
      <CardHeader className="flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="grid gap-1">
          <CardTitle className="flex items-center gap-2">
            <ListTree className="size-4 text-primary" aria-hidden />
            Journal des requêtes
            <LiveIndicator className="ml-1" />
          </CardTitle>
          <CardDescription className="text-xs">
            Toutes périodes, de la plus récente à la plus ancienne : chaque ligne s&apos;ouvre dans l&apos;explorateur avec ses
            éléments retenus, exclus et sa cascade des temps.
          </CardDescription>
        </div>
        <SimpleSelect
          size="sm"
          value={agent}
          onValueChange={(v) => {
            setAgent(v);
            setPage(1);
          }}
          options={options}
          className="sm:w-56"
          aria-label="Filtrer le journal par agent"
        />
      </CardHeader>
      {requests.isError ? (
        <div className="px-5 pb-5">
          <ErrorState size="sm" error={requests.error} onRetry={() => void requests.refetch()} />
        </div>
      ) : (
        <>
          <Table dense className={cn(requests.isPlaceholderData && "opacity-60")}>
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead>
                <TableHead>Tâche</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Utilisateur</TableHead>
                <TableHead className="text-right">Latence</TableHead>
                <TableHead>Tokens / budget</TableHead>
                <TableHead className="text-right">Retenus / exclus</TableHead>
                <TableHead>Snapshot</TableHead>
                <TableHead>Note</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {requests.isPending ? (
                Array.from({ length: 6 }, (_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={COLUMNS}>
                      <Skeleton className="h-5 w-full" />
                    </TableCell>
                  </TableRow>
                ))
              ) : requests.data.items.length === 0 ? (
                <TableEmptyRow colSpan={COLUMNS}>Aucune requête de contexte pour ce filtre.</TableEmptyRow>
              ) : (
                requests.data.items.map((r) => <LogRow key={r.id} request={r} slug={slug} fresh={page === 1 && fresh.has(r.id)} />)
              )}
            </TableBody>
          </Table>
          {requests.data && requests.data.total > 0 ? (
            <div className="border-t border-border px-4 py-3">
              <Pagination
                page={requests.data.page}
                pageSize={requests.data.page_size}
                total={requests.data.total}
                onPageChange={setPage}
                disabled={requests.isFetching}
              />
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
}
