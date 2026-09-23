"use client";

import * as React from "react";

import { formatDateTime, formatRelative, toDate } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface RelativeTimeProps {
  date: string | number | Date | null | undefined;
  className?: string;
  /** Refresh interval in ms (default 60 s). */
  refreshMs?: number;
  /** Text shown when the date is missing. */
  fallback?: string;
}

/** "il y a 3 minutes" (fr), with the absolute date in the tooltip/title; refreshes periodically. */
export function RelativeTime({ date, className, refreshMs = 60_000, fallback = "—" }: RelativeTimeProps) {
  const d = toDate(date);
  const [, force] = React.useReducer((x: number) => x + 1, 0);

  React.useEffect(() => {
    if (!d) return;
    const id = window.setInterval(force, refreshMs);
    return () => window.clearInterval(id);
  }, [d, refreshMs]);

  if (!d) return <span className={cn("text-subtle-foreground", className)}>{fallback}</span>;
  return (
    <time
      dateTime={d.toISOString()}
      title={formatDateTime(d)}
      className={cn("whitespace-nowrap tabular-nums", className)}
      suppressHydrationWarning
    >
      {formatRelative(d)}
    </time>
  );
}
