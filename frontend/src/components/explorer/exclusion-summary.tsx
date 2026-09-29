"use client";

import { ShieldCheck } from "lucide-react";

import { REASON_CODE_META, REASON_GROUP_META, type ReasonCode, type ReasonGroup } from "@/lib/enums";
import type { ExclusionSummaryEntry } from "@/lib/explorer-utils";
import { formatNumber, formatPercent } from "@/lib/format";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

export interface ExclusionSummaryProps {
  entries: ExclusionSummaryEntry[];
  includedCount: number;
  onSelect?: (code: string) => void;
  className?: string;
}

const LEGEND_GROUPS: ReasonGroup[] = ["governance", "quality", "efficiency"];

/**
 * Exclusions by reason as labelled horizontal bars (tone = reason family: governance / quality / efficiency).
 * Each row is a button that jumps to the matching group in the "Exclus" column.
 */
export function ExclusionSummary({ entries, includedCount, onSelect, className }: ExclusionSummaryProps) {
  const totalExcluded = entries.reduce((acc, e) => acc + e.count, 0);
  const candidates = totalExcluded + includedCount;

  if (entries.length === 0) {
    return (
      <div className={cn("flex items-center gap-2 text-[13px] text-muted-foreground", className)}>
        <ShieldCheck className="size-4 text-primary" aria-hidden />
        Aucun candidat exclu.
      </div>
    );
  }

  const presentGroups = new Set(entries.map((e) => REASON_CODE_META[e.code as ReasonCode]?.group).filter(Boolean));

  return (
    <div className={cn("grid gap-3", className)}>
      <div className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
        <span>
          <span className="text-lg font-semibold tabular-nums text-foreground">{formatNumber(totalExcluded, 0)}</span> exclus
          {candidates > 0 ? <> sur {formatNumber(candidates, 0)} candidats</> : null}
        </span>
        {candidates > 0 ? <span className="tabular-nums">{formatPercent(totalExcluded / candidates)} d&apos;exclusion</span> : null}
      </div>
      <ul className="grid gap-1" aria-label="Exclusions par motif">
        {entries.map((entry) => {
          const meta = REASON_CODE_META[entry.code as ReasonCode];
          const t = toneClasses(meta?.tone);
          const label = meta?.short ?? entry.code;
          const content = (
            <>
              <span className="w-24 shrink-0 truncate text-left text-muted-foreground group-hover:text-foreground">{label}</span>
              <span className="relative h-2.5 flex-1 overflow-hidden rounded-full bg-muted/70" aria-hidden>
                <span
                  className={cn("absolute inset-y-0 left-0 rounded-full transition-[width] duration-500", t.bar)}
                  style={{ width: `${Math.max(entry.ratio * 100, 4)}%` }}
                />
              </span>
              <span className="w-7 shrink-0 text-right font-semibold tabular-nums text-foreground">{formatNumber(entry.count, 0)}</span>
            </>
          );
          return (
            <li key={entry.code}>
              {onSelect ? (
                <button
                  type="button"
                  onClick={() => onSelect(entry.code)}
                  className="group flex w-full items-center gap-2.5 rounded-md px-1.5 py-1 text-xs hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  aria-label={`${meta?.label ?? entry.code} : ${entry.count}`}
                  title={meta?.label}
                >
                  {content}
                </button>
              ) : (
                <div className="flex items-center gap-2.5 px-1.5 py-1 text-xs" title={meta?.label}>
                  {content}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <ul className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground" aria-label="Familles de motifs">
        {LEGEND_GROUPS.filter((g) => presentGroups.has(g)).map((g) => (
          <li key={g} className="flex items-center gap-1.5" title={REASON_GROUP_META[g].description}>
            <span className={cn("size-2.5 rounded-[3px]", toneClasses(REASON_GROUP_META[g].tone).bar)} aria-hidden />
            {REASON_GROUP_META[g].label}
          </li>
        ))}
      </ul>
    </div>
  );
}
