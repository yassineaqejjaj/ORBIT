"use client";

import * as React from "react";
import Link from "next/link";
import { Bot, FileStack } from "lucide-react";

import { AgentKindBadge } from "@/components/domain/enum-badge";
import { SourceKindIcon } from "@/components/domain/source-kind-icon";
import { Table, TableBody, TableCell, TableEmptyRow, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { MetricsByAgent, MetricsTopSource } from "@/lib/api/types";
import { formatMs, formatNumber, formatTokens } from "@/lib/format";
import { ChartCard } from "./chart-card";

export function AgentsTable({ rows, loading }: { rows: MetricsByAgent[]; loading?: boolean }) {
  const sorted = React.useMemo(() => [...rows].sort((a, b) => b.requests - a.requests), [rows]);
  const max = Math.max(1, ...sorted.map((r) => r.requests));
  return (
    <ChartCard
      title="Par agent"
      description="Volume, latence et taille moyenne des contextes servis à chaque agent."
      icon={<Bot aria-hidden />}
      loading={loading}
      height={200}
      contentClassName="px-0 pb-2"
    >
      <Table dense>
        <TableHeader>
          <TableRow>
            <TableHead>Agent</TableHead>
            <TableHead className="text-right">Requêtes</TableHead>
            <TableHead className="text-right">Latence moy.</TableHead>
            <TableHead className="text-right">Tokens moy.</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.length === 0 ? (
            <TableEmptyRow colSpan={4}>Aucune requête d&apos;agent sur la période.</TableEmptyRow>
          ) : (
            sorted.map((r) => (
              <TableRow key={r.agent_id}>
                <TableCell>
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate font-medium text-foreground">{r.name}</span>
                    <AgentKindBadge value={r.kind} />
                  </div>
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex items-center justify-end gap-2">
                    <span className="hidden h-1.5 w-16 overflow-hidden rounded-full bg-muted sm:block" aria-hidden>
                      <span className="block h-full rounded-full bg-chart-1" style={{ width: `${(r.requests / max) * 100}%` }} />
                    </span>
                    <span className="w-8 font-medium tabular-nums">{formatNumber(r.requests, 0)}</span>
                  </div>
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatMs(r.avg_latency_ms)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatTokens(r.avg_tokens, { unit: false })}</TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </ChartCard>
  );
}

export function TopSourcesTable({ rows, slug, loading }: { rows: MetricsTopSource[]; slug: string; loading?: boolean }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <ChartCard
      title="Sources les plus utilisées"
      description="Documents dont les extraits ont été le plus souvent retenus."
      icon={<FileStack aria-hidden />}
      loading={loading}
      height={200}
      contentClassName="px-0 pb-2"
    >
      <Table dense>
        <TableHeader>
          <TableRow>
            <TableHead className="w-8">#</TableHead>
            <TableHead>Document</TableHead>
            <TableHead className="text-right">Citations</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableEmptyRow colSpan={3}>Aucun extrait de source servi sur la période.</TableEmptyRow>
          ) : (
            rows.map((r, i) => (
              <TableRow key={r.document_id}>
                <TableCell className="tabular-nums text-subtle-foreground">{i + 1}</TableCell>
                <TableCell>
                  <Link
                    href={`/projects/${encodeURIComponent(slug)}/sources/${encodeURIComponent(r.document_id)}`}
                    className="flex min-w-0 items-center gap-2 font-medium text-foreground hover:text-primary hover:underline hover:underline-offset-2"
                  >
                    <SourceKindIcon kind={r.source_kind} size="sm" />
                    <span className="truncate">{r.title}</span>
                  </Link>
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex items-center justify-end gap-2">
                    <span className="hidden h-1.5 w-16 overflow-hidden rounded-full bg-muted sm:block" aria-hidden>
                      <span className="block h-full rounded-full bg-chart-3" style={{ width: `${(r.count / max) * 100}%` }} />
                    </span>
                    <span className="w-8 font-medium tabular-nums">{formatNumber(r.count, 0)}</span>
                  </div>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </ChartCard>
  );
}
