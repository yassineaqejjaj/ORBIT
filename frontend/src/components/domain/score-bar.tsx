import type { Tone } from "@/lib/enums";
import { formatScore } from "@/lib/format";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

export interface ScoreBarProps {
  /** Score value (default range 0..1). */
  value: number | null | undefined;
  max?: number;
  /** Optional label on the left (e.g. "BM25"). */
  label?: string;
  showValue?: boolean;
  /** Fixed tone; defaults to a value-based tone (≥ 0,7 teal, ≥ 0,4 blue, else slate). */
  tone?: Tone;
  /** Draws a threshold tick (e.g. min_relevance 0,35). */
  threshold?: number;
  /** Width class of the bar track. */
  widthClassName?: string;
  className?: string;
}

function autoTone(ratio: number): Tone {
  if (ratio >= 0.7) return "teal";
  if (ratio >= 0.4) return "blue";
  return "neutral";
}

/** Compact horizontal score bar with the numeric value (FR decimal). */
export function ScoreBar({
  value,
  max = 1,
  label,
  showValue = true,
  tone,
  threshold,
  widthClassName = "w-16",
  className,
}: ScoreBarProps) {
  const valid = typeof value === "number" && Number.isFinite(value);
  const ratio = valid ? Math.max(0, Math.min(1, value / (max || 1))) : 0;
  const t = toneClasses(tone ?? autoTone(ratio));
  const thresholdRatio = typeof threshold === "number" ? Math.max(0, Math.min(1, threshold / (max || 1))) : null;

  return (
    <span className={cn("inline-flex items-center gap-2 text-xs", className)}>
      {label ? <span className="w-12 shrink-0 truncate text-muted-foreground">{label}</span> : null}
      <span
        className={cn("relative h-1.5 shrink-0 overflow-hidden rounded-full", t.track, widthClassName)}
        role="meter"
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={valid ? value : undefined}
        aria-label={label ?? "Score"}
      >
        <span className={cn("absolute inset-y-0 left-0 rounded-full", t.bar)} style={{ width: `${ratio * 100}%` }} />
        {thresholdRatio !== null ? (
          <span
            className="absolute inset-y-[-2px] w-px bg-foreground/50"
            style={{ left: `${thresholdRatio * 100}%` }}
            aria-hidden
          />
        ) : null}
      </span>
      {showValue ? (
        <span className="w-8 shrink-0 text-right font-medium tabular-nums text-foreground">
          {valid ? formatScore(value) : "—"}
        </span>
      ) : null}
    </span>
  );
}
