"use client";

import * as React from "react";
import { Bot, Camera, History, Timer, UserRound } from "lucide-react";

import { RelativeTime } from "@/components/domain/relative-time";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Pagination } from "@/components/ui/pagination";
import { SimpleSelect } from "@/components/ui/select";
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useAgents, useContextRequests } from "@/lib/api/hooks";
import type { ContextRequestSummary } from "@/lib/api/types";
import { formatMs, formatNumber } from "@/lib/format";
import { LiveIndicator } from "@/components/layout/live-indicator";
import { useFreshIds, useLivePollInterval } from "@/lib/live/live-events";
import { cn } from "@/lib/utils";
import { StarRating } from "./star-rating";

const ALL_AGENTS = "all";

export interface HistoryDrawerProps {
  slug: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  activeRequestId: string | null;
  onSelect: (request: ContextRequestSummary) => void;
}

function HistoryRow({
  request,
  active,
  onSelect,
  fresh,
}: {
  request: ContextRequestSummary;
  active: boolean;
  onSelect: () => void;
  fresh?: boolean;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={active ? "true" : undefined}
        className={cn(
          "grid w-full gap-1.5 rounded-lg border px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          fresh && "live-flash",
          active ? "border-primary/50 bg-brand-soft/50" : "border-border bg-card hover:border-border-strong hover:bg-muted/40",
        )}
      >
        <p className="line-clamp-2 text-[13px] font-medium leading-snug text-foreground">{request.task}</p>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            {request.agent ? <Bot className="size-3.5" aria-hidden /> : <UserRound className="size-3.5" aria-hidden />}
            <span className="font-medium text-foreground/80">{request.agent?.name ?? request.user?.full_name ?? "Humain"}</span>
            {request.agent && request.user ? <span>· {request.user.full_name}</span> : null}
          </span>
          <RelativeTime date={request.created_at} />
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] tabular-nums text-muted-foreground">
          <span>
            <span className="font-medium text-foreground">{formatNumber(request.tokens_used, 0)}</span> / {formatNumber(request.token_budget, 0)}{" "}
            tokens
          </span>
          <span>
            <span className="font-medium text-primary">{formatNumber(request.included_count, 0)}</span> retenus ·{" "}
            {formatNumber(request.excluded_count, 0)} exclus
          </span>
          <span className="inline-flex items-center gap-1">
            <Timer className="size-3" aria-hidden />
            {formatMs(request.latency_ms)}
          </span>
          {request.snapshot ? (
            <Badge tone="violet" icon={<Camera aria-hidden />}>
              {request.snapshot.name} · v{request.snapshot.version}
            </Badge>
          ) : null}
          {typeof request.rating === "number" ? <StarRating value={request.rating} className="ml-auto" /> : null}
        </div>
      </button>
    </li>
  );
}

/** Recent context requests of the project; selecting one reloads its stored result in the explorer. */
export function HistoryDrawer({ slug, open, onOpenChange, activeRequestId, onSelect }: HistoryDrawerProps) {
  const [page, setPage] = React.useState(1);
  const [agentFilter, setAgentFilter] = React.useState<string>(ALL_AGENTS);
  const agents = useAgents(slug, { enabled: open });
  const poll = useLivePollInterval();
  const requests = useContextRequests(
    slug,
    { page, ...(agentFilter !== ALL_AGENTS ? { agent_id: agentFilter } : {}) },
    { enabled: open, refetchInterval: poll },
  );
  const fresh = useFreshIds(
    (requests.data?.items ?? []).map((r) => r.id),
    `${page}:${agentFilter}`,
  );

  const agentOptions = React.useMemo(
    () => [
      { value: ALL_AGENTS, label: "Tous les demandeurs" },
      ...(agents.data ?? []).map((a) => ({ value: a.id, label: a.name })),
    ],
    [agents.data],
  );

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" size="md">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <History className="size-4 text-primary" aria-hidden />
            Historique des contextes
            <LiveIndicator className="ml-1" />
          </SheetTitle>
          <SheetDescription>Rouvrez une requête passée : résultat, exclusions et cascade des temps sont reconstitués.</SheetDescription>
        </SheetHeader>
        <div className="border-b border-border px-5 py-3">
          <SimpleSelect
            size="sm"
            value={agentFilter}
            onValueChange={(v) => {
              setAgentFilter(v);
              setPage(1);
            }}
            options={agentOptions}
            aria-label="Filtrer par agent"
          />
        </div>
        <SheetBody>
          {requests.isPending ? (
            <div className="grid gap-2" aria-busy="true" aria-label="Chargement de l'historique">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-24 rounded-lg" />
              ))}
            </div>
          ) : requests.isError ? (
            <ErrorState size="sm" error={requests.error} onRetry={() => void requests.refetch()} />
          ) : requests.data.items.length === 0 ? (
            <EmptyState
              size="sm"
              icon={<History />}
              title="Aucune requête"
              description="Les contextes assemblés (par vous ou par les agents) apparaîtront ici."
            />
          ) : (
            <ul className={cn("grid gap-2", requests.isPlaceholderData && "opacity-60")}>
              {requests.data.items.map((r) => (
                <HistoryRow
                key={r.id}
                request={r}
                active={r.id === activeRequestId}
                fresh={page === 1 && fresh.has(r.id)}
                onSelect={() => onSelect(r)}
              />
              ))}
            </ul>
          )}
        </SheetBody>
        {requests.data && requests.data.total > requests.data.page_size ? (
          <SheetFooter className="sm:justify-center">
            <Pagination
              compact
              page={requests.data.page}
              pageSize={requests.data.page_size}
              total={requests.data.total}
              onPageChange={setPage}
              disabled={requests.isFetching}
              className="w-full"
            />
          </SheetFooter>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
