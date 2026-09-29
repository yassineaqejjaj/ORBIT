import * as React from "react";
import { BarChart3 } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export interface ChartCardProps {
  title: string;
  description?: React.ReactNode;
  icon?: React.ReactNode;
  /** Right-aligned header content (headline value, legend…). */
  aside?: React.ReactNode;
  loading?: boolean;
  /** Renders the empty placeholder instead of `children`. */
  empty?: boolean;
  emptyText?: string;
  /** Plot height used by the loading / empty placeholders. */
  height?: number;
  className?: string;
  contentClassName?: string;
  children?: React.ReactNode;
}

/** Card frame shared by every observability chart and table (title, description, loading and empty states). */
export function ChartCard({
  title,
  description,
  icon,
  aside,
  loading,
  empty,
  emptyText = "Aucune donnée sur la période.",
  height = 220,
  className,
  contentClassName,
  children,
}: ChartCardProps) {
  return (
    <Card className={cn("flex min-w-0 flex-col", className)}>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div className="grid min-w-0 gap-1">
          <CardTitle className="flex items-center gap-2 [&_svg]:size-4 [&_svg]:text-primary">
            {icon}
            {title}
          </CardTitle>
          {description ? <CardDescription className="text-xs">{description}</CardDescription> : null}
        </div>
        {aside && !loading ? <div className="shrink-0 text-right">{aside}</div> : null}
      </CardHeader>
      <CardContent className={cn("min-w-0 flex-1", contentClassName)}>
        {loading ? (
          <Skeleton className="w-full rounded-lg" style={{ height }} />
        ) : empty ? (
          <div
            className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border text-center text-[13px] text-muted-foreground"
            style={{ height }}
          >
            <BarChart3 className="size-5 text-subtle-foreground" aria-hidden />
            {emptyText}
          </div>
        ) : (
          children
        )}
      </CardContent>
    </Card>
  );
}

/** Headline value displayed in a ChartCard aside. */
export function ChartHeadline({ value, label }: { value: React.ReactNode; label: string }) {
  return (
    <div className="grid gap-0.5">
      <span className="text-lg font-semibold leading-none tracking-tight text-foreground">{value}</span>
      <span className="text-[11px] text-muted-foreground">{label}</span>
    </div>
  );
}
