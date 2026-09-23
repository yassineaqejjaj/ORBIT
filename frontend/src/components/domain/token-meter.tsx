import type { Tone } from "@/lib/enums";
import { formatNumber, formatPercent } from "@/lib/format";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

export interface TokenMeterProps {
  used: number | null | undefined;
  budget: number | null | undefined;
  /** Show "3 420 / 4 000 tokens · 86 %". */
  showLabel?: boolean;
  size?: "sm" | "md";
  className?: string;
}

/** Token budget usage (teal < 85 %, amber ≤ 100 %, red when over budget). */
export function TokenMeter({ used, budget, showLabel = true, size = "sm", className }: TokenMeterProps) {
  const u = typeof used === "number" && Number.isFinite(used) ? used : 0;
  const b = typeof budget === "number" && Number.isFinite(budget) && budget > 0 ? budget : 0;
  const ratio = b > 0 ? u / b : 0;
  const tone: Tone = ratio > 1 ? "red" : ratio >= 0.85 ? "amber" : "teal";
  const t = toneClasses(tone);

  return (
    <div className={cn("grid min-w-32 gap-1", className)}>
      {showLabel ? (
        <div className="flex items-baseline justify-between gap-2 text-xs">
          <span className="tabular-nums text-foreground">
            <span className="font-semibold">{formatNumber(u, 0)}</span>
            <span className="text-muted-foreground"> / {b ? formatNumber(b, 0) : "—"} tokens</span>
          </span>
          <span className={cn("font-medium tabular-nums", t.text)}>{b ? formatPercent(ratio) : "—"}</span>
        </div>
      ) : null}
      <div
        className={cn("relative overflow-hidden rounded-full", size === "sm" ? "h-1.5" : "h-2", t.track)}
        role="meter"
        aria-label="Budget de tokens utilisé"
        aria-valuemin={0}
        aria-valuemax={b || undefined}
        aria-valuenow={u}
        aria-valuetext={b ? `${formatNumber(u, 0)} tokens sur ${formatNumber(b, 0)}` : `${formatNumber(u, 0)} tokens`}
      >
        <div
          className={cn("h-full rounded-full transition-[width] duration-500", t.bar)}
          style={{ width: `${Math.min(1, ratio) * 100}%` }}
        />
      </div>
    </div>
  );
}
