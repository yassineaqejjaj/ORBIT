"use client";

import * as React from "react";
import { ChevronDown, Table2 } from "lucide-react";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatCost, formatDate, formatMs, formatNumber } from "@/lib/format";
import type { DailyPoint } from "@/lib/observability-utils";
import { cn } from "@/lib/utils";

/**
 * Table twin of the daily charts (requests, latency, tokens, cost): every charted value stays
 * readable without hovering, for keyboard and screen-reader users.
 */
export function DailyTable({ data, className }: { data: DailyPoint[]; className?: string }) {
  const [open, setOpen] = React.useState(false);
  const panelId = React.useId();
  const rows = React.useMemo(() => [...data].reverse(), [data]);

  return (
    <div className={cn("rounded-xl border border-border bg-card shadow-xs", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex w-full items-center gap-2 rounded-xl px-4 py-2.5 text-left text-[13px] font-medium text-foreground hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Table2 className="size-4 text-primary" aria-hidden />
        Données journalières (tableau)
        <span className="text-xs font-normal text-muted-foreground">— valeurs exactes des graphiques ci-dessus</span>
        <ChevronDown
          className={cn("ml-auto size-4 text-subtle-foreground transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>
      {open ? (
        <div id={panelId} className="border-t border-border">
          <Table dense containerClassName="max-h-96">
            <TableHeader>
              <TableRow>
                <TableHead>Jour</TableHead>
                <TableHead className="text-right">Requêtes</TableHead>
                <TableHead className="text-right">Latence p50</TableHead>
                <TableHead className="text-right">Latence p95</TableHead>
                <TableHead className="text-right">Tokens servis</TableHead>
                <TableHead className="text-right">Coût estimé</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((d) => (
                <TableRow key={d.date}>
                  <TableCell className="whitespace-nowrap">{formatDate(d.date)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatNumber(d.requests, 0)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatMs(d.p50)}</TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      typeof d.p95 === "number" && d.p95 > 1500 && "text-amber-700 dark:text-amber-300",
                    )}
                  >
                    {formatMs(d.p95)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{formatNumber(d.tokens, 0)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatCost(d.cost)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}
    </div>
  );
}
