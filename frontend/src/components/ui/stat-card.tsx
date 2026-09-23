import * as React from "react";
import Link from "next/link";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";

import type { Tone } from "@/lib/enums";
import { formatPercent } from "@/lib/format";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";
import { Skeleton } from "./skeleton";

export interface StatCardDelta {
  /** Relative change as a ratio (0.12 = +12 %). */
  value: number;
  /** e.g. "vs 7 j précédents". */
  label?: string;
  /** Whether an increase is good (green) — default true. */
  positiveIsGood?: boolean;
}

export interface StatCardProps {
  label: React.ReactNode;
  value: React.ReactNode;
  /** Lucide icon element. */
  icon?: React.ReactNode;
  /** Tone of the icon chip. */
  tone?: Tone;
  /** Secondary line under the value. */
  hint?: React.ReactNode;
  delta?: StatCardDelta;
  loading?: boolean;
  /** Makes the whole card a link. */
  href?: string;
  className?: string;
  /** Extra content under the value (sparkline, progress…). */
  children?: React.ReactNode;
}

export function StatCard({ label, value, icon, tone = "teal", hint, delta, loading, href, className, children }: StatCardProps) {
  const t = toneClasses(tone);
  const up = delta ? delta.value >= 0 : false;
  const good = delta ? (delta.positiveIsGood ?? true) === up : false;

  const body = (
    <div
      className={cn(
        "group relative flex h-full flex-col gap-3 rounded-xl border border-border bg-card p-4 shadow-xs",
        href && "transition-[border-color,box-shadow] hover:border-border-strong hover:shadow-md",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[12.5px] font-medium text-muted-foreground">{label}</p>
        {icon ? (
          <span className={cn("flex size-7 items-center justify-center rounded-lg ring-1 ring-inset [&_svg]:size-3.5", t.soft)} aria-hidden>
            {icon}
          </span>
        ) : null}
      </div>
      <div className="grid gap-1">
        {loading ? (
          <Skeleton className="h-7 w-24" />
        ) : (
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="text-2xl font-semibold tracking-tight tabular-nums text-foreground">{value}</span>
            {delta ? (
              <span
                className={cn(
                  "inline-flex items-center gap-0.5 text-xs font-medium tabular-nums",
                  good ? "text-emerald-700 dark:text-emerald-400" : "text-red-700 dark:text-red-400",
                )}
              >
                {up ? <ArrowUpRight className="size-3.5" aria-hidden /> : <ArrowDownRight className="size-3.5" aria-hidden />}
                {formatPercent(Math.abs(delta.value))}
                {delta.label ? <span className="font-normal text-muted-foreground">&nbsp;{delta.label}</span> : null}
              </span>
            ) : null}
          </div>
        )}
        {hint ? (
          loading ? (
            <Skeleton className="h-3 w-32" />
          ) : (
            <div className="text-xs text-muted-foreground">{hint}</div>
          )
        ) : null}
      </div>
      {children}
    </div>
  );

  if (href) {
    return (
      <Link href={href} className="block rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {body}
      </Link>
    );
  }
  return body;
}
