"use client";

import * as React from "react";
import { Gauge } from "lucide-react";

import { ScoreBar } from "@/components/domain/score-bar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { Scores } from "@/lib/api/types";
import { scoreRows } from "@/lib/explorer-utils";
import { formatScore } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface ScoresPopoverProps {
  scores: Scores;
  /** Scale used for the BM25 bar (package maximum). */
  bm25Max?: number;
  /** Relevance threshold drawn on the final bar. */
  threshold?: number;
  className?: string;
}

/** "Score 0,82" trigger opening the detailed scores (BM25, dense, RRF, rerank, fraîcheur, final). */
export function ScoresPopover({ scores, bm25Max = 1, threshold, className }: ScoresPopoverProps) {
  const rows = scoreRows(scores, bm25Max);
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex h-5 items-center gap-1 rounded-md px-1.5 text-[11px] font-medium text-muted-foreground ring-1 ring-inset ring-border transition-colors",
            "hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            className,
          )}
          aria-label={`Détail des scores (final ${formatScore(scores.final)})`}
        >
          <Gauge className="size-3" aria-hidden />
          <span className="tabular-nums">{formatScore(scores.final)}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-3">
        <p className="text-[13px] font-semibold">Détail des scores</p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Score final = 0,55·RRF + 0,20·dense + 0,10·fraîcheur + 0,10·type + 0,05·termes.
        </p>
        <ul className="mt-3 grid gap-2">
          {rows.map((row) => (
            <li key={row.key} className={cn("grid gap-0.5", row.key === "final" && "border-t border-border pt-2")}>
              <ScoreBar
                value={row.value}
                max={row.max}
                label={row.label}
                widthClassName="flex-1"
                className="w-full"
                tone={row.key === "final" ? "teal" : undefined}
                threshold={row.key === "final" ? threshold : undefined}
              />
              <span className="pl-14 text-[11px] text-subtle-foreground">
                {row.hint}
                {row.key === "bm25" && typeof row.value === "number" && row.max > 1 ? " · échelle relative au paquet" : ""}
                {row.value === undefined ? " · non calculé" : ""}
              </span>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
