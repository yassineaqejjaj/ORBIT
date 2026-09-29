import * as React from "react";
import { Timer } from "lucide-react";

import { SimpleTooltip } from "@/components/ui/tooltip";
import type { ContextTimings } from "@/lib/api/types";
import { buildStageWaterfall } from "@/lib/explorer-utils";
import { formatMs, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface StageWaterfallProps {
  timings: Partial<ContextTimings> | null | undefined;
  className?: string;
}

/**
 * Horizontal waterfall of the assembly stages: each bar starts where the previous stage ended,
 * its width is proportional to the stage duration. The slowest stage is emphasized.
 */
export function StageWaterfall({ timings, className }: StageWaterfallProps) {
  const { total, segments, slowest } = React.useMemo(() => buildStageWaterfall(timings), [timings]);

  if (total <= 0) {
    return <p className={cn("text-[13px] text-muted-foreground", className)}>Aucune mesure de temps disponible pour cette requête.</p>;
  }

  return (
    <div className={cn("grid gap-2", className)}>
      <ol className="grid gap-1.5" aria-label={`Cascade des étapes, total ${formatMs(total)}`}>
        {segments.map((s) => {
          const isSlowest = s.key === slowest;
          const overhead = s.key === "overhead";
          return (
            <li key={s.key} className="grid grid-cols-[6.5rem_1fr_4.25rem] items-center gap-3 text-xs sm:grid-cols-[8rem_1fr_4.5rem]">
              <SimpleTooltip content={s.description} side="left">
                <span className={cn("truncate", isSlowest ? "font-semibold text-foreground" : "text-muted-foreground")}>
                  {s.label}
                </span>
              </SimpleTooltip>
              <div className="relative h-4 rounded-sm bg-muted/60" aria-hidden>
                <div
                  className={cn(
                    "absolute inset-y-0 min-w-[3px] rounded-[4px] transition-[left,width] duration-500",
                    overhead
                      ? "bg-slate-300 dark:bg-slate-600"
                      : isSlowest
                        ? "bg-primary"
                        : "bg-primary/45 dark:bg-primary/55",
                  )}
                  style={{ left: `${s.startRatio * 100}%`, width: `${Math.max(s.widthRatio * 100, 0)}%` }}
                />
              </div>
              <span className="text-right font-medium tabular-nums text-foreground">
                {formatMs(s.duration)}
                <span className="sr-only"> ({formatPercent(s.widthRatio)} du total)</span>
              </span>
            </li>
          );
        })}
      </ol>
      <div className="grid grid-cols-[6.5rem_1fr_4.25rem] items-center gap-3 border-t border-border pt-2 text-xs sm:grid-cols-[8rem_1fr_4.5rem]">
        <span className="inline-flex items-center gap-1.5 font-semibold text-foreground">
          <Timer className="size-3.5 text-primary" aria-hidden />
          Total
        </span>
        <div className="flex justify-between text-[10.5px] tabular-nums text-subtle-foreground" aria-hidden>
          <span>0</span>
          <span>{formatMs(total / 2)}</span>
          <span>{formatMs(total)}</span>
        </div>
        <span className="text-right font-semibold tabular-nums text-foreground">{formatMs(total)}</span>
      </div>
    </div>
  );
}
