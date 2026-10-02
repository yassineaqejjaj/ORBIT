"use client";

import Link from "next/link";
import { CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { OverviewAlert } from "@/lib/api/types";
import { ALERT_LEVEL_META, type AlertLevel } from "@/lib/enums";
import { cn } from "@/lib/utils";
import { alertLink } from "./attention-links";
import { sortAlerts, splitAlertMessage } from "./project-health";

const LEVEL_STYLE: Record<AlertLevel, { icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>; className: string }> = {
  critical: { icon: CircleAlert, className: "text-red-600 dark:text-red-400" },
  warning: { icon: TriangleAlert, className: "text-amber-600 dark:text-amber-400" },
  info: { icon: Info, className: "text-sky-600 dark:text-sky-400" },
};

/** Level 1 — "Y a-t-il quelque chose qui demande mon attention ?" Compact, actionable list (critical → info). */
export function AttentionList({ slug, alerts, className }: { slug: string; alerts: readonly OverviewAlert[]; className?: string }) {
  const sorted = sortAlerts(alerts);
  return (
    <Card className={cn("flex flex-col", className)}>
      <CardHeader>
        <CardTitle>À traiter</CardTitle>
      </CardHeader>
      <CardContent className="flex-1">
        {sorted.length === 0 ? (
          <p className="flex items-center gap-2 rounded-lg border border-dashed border-border px-3 py-4 text-[13px] text-muted-foreground">
            <CircleCheck className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />
            Aucun élément ne demande votre attention.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {sorted.map((alert, index) => {
              const style = LEVEL_STYLE[alert.level] ?? LEVEL_STYLE.info;
              const LevelIcon = style.icon;
              const levelLabel = ALERT_LEVEL_META[alert.level]?.label ?? "Information";
              const { title, description } = splitAlertMessage(alert.message);
              const link = alertLink(slug, alert.message);
              return (
                <li key={`${alert.level}-${index}`} className="flex items-start gap-3 py-2.5 first:pt-0 last:pb-0">
                  <LevelIcon className={cn("mt-0.5 size-4 shrink-0", style.className)} aria-hidden />
                  <div className="grid min-w-0 flex-1 gap-0.5">
                    <p className="text-[13px] font-medium leading-snug text-foreground">
                      <span className="sr-only">{levelLabel} : </span>
                      {title}
                    </p>
                    {description ? <p className="text-xs leading-snug text-muted-foreground">{description}</p> : null}
                  </div>
                  {link ? (
                    <Link
                      href={link.href}
                      className="shrink-0 rounded-md px-2 py-1 text-xs font-medium text-primary transition-colors hover:bg-brand-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                      aria-label={`${link.label} — ${title}`}
                    >
                      {link.cta}
                    </Link>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
