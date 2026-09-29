"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, BellRing, CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";

import { projectHref } from "@/components/layout/nav";
import { Badge } from "@/components/ui/badge";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { OverviewAlert } from "@/lib/api/types";
import { ALERT_LEVEL_META, ALERT_LEVELS, type AlertLevel } from "@/lib/enums";
import { toneClasses } from "@/lib/tones";
import { cn, normalizeText } from "@/lib/utils";

const LEVEL_ICONS: Record<AlertLevel, React.ReactNode> = {
  critical: <CircleAlert aria-hidden />,
  warning: <TriangleAlert aria-hidden />,
  info: <Info aria-hidden />,
};

const LEVEL_ORDER: Record<AlertLevel, number> = { critical: 0, warning: 1, info: 2 };

interface AlertLink {
  href: string;
  label: string;
}

/** Best-effort link from an alert message to the screen where it can be handled. */
export function alertLink(slug: string, message: string): AlertLink | null {
  const text = normalizeText(message);
  if (/(echec|echoue|failed|erreur)/.test(text)) {
    return { href: `${projectHref(slug, "sources")}?tab=jobs&job_status=failed`, label: "Voir les traitements" };
  }
  if (/(conflit|contradi)/.test(text)) {
    return { href: `${projectHref(slug, "memory")}`, label: "Examiner la mémoire" };
  }
  if (/(propos|a valider|en attente de validation)/.test(text)) {
    return { href: `${projectHref(slug, "memory")}?status=proposed`, label: "Revoir les propositions" };
  }
  if (/\bc3\b|secret/.test(text)) {
    return { href: `${projectHref(slug, "sources")}?classification=3`, label: "Voir les documents C3" };
  }
  if (/\bc2\b|confidentiel|classifi/.test(text)) {
    return { href: `${projectHref(slug, "sources")}?classification=2`, label: "Voir les documents C2" };
  }
  if (/(donnees personnelles|pii)/.test(text)) {
    return { href: `${projectHref(slug, "sources")}`, label: "Voir les sources" };
  }
  if (/(perime|fraicheur|obsolete)/.test(text)) {
    return { href: `${projectHref(slug, "settings")}?tab=project`, label: "Politiques de fraîcheur" };
  }
  if (/(en attente|en cours|file)/.test(text)) {
    return { href: `${projectHref(slug, "sources")}?tab=jobs`, label: "Suivre l'ingestion" };
  }
  return null;
}

export function AlertsCard({ slug, alerts, className }: { slug: string; alerts: readonly OverviewAlert[]; className?: string }) {
  const sorted = React.useMemo(
    () => [...alerts].sort((a, b) => (LEVEL_ORDER[a.level] ?? 3) - (LEVEL_ORDER[b.level] ?? 3)),
    [alerts],
  );
  const counts = React.useMemo(() => {
    const c: Record<AlertLevel, number> = { critical: 0, warning: 0, info: 0 };
    for (const a of alerts) if (a.level in c) c[a.level] += 1;
    return c;
  }, [alerts]);

  return (
    <Card className={cn("flex flex-col", className)}>
      <CardHeader className="flex-row items-center gap-2">
        <BellRing className="size-4 text-muted-foreground" aria-hidden />
        <CardTitle>Alertes de gouvernance</CardTitle>
        <CardAction>
          {ALERT_LEVELS.filter((l) => counts[l] > 0)
            .sort((a, b) => LEVEL_ORDER[a] - LEVEL_ORDER[b])
            .map((l) => (
              <Badge key={l} tone={ALERT_LEVEL_META[l].tone} size="sm" dot>
                {counts[l]} {ALERT_LEVEL_META[l].label.toLowerCase()}
              </Badge>
            ))}
        </CardAction>
      </CardHeader>
      <CardContent className="flex-1">
        {sorted.length === 0 ? (
          <div className="flex h-full min-h-28 items-center gap-3 rounded-lg border border-dashed border-border px-4 py-5">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-600/20 dark:bg-emerald-400/10 dark:text-emerald-300 dark:ring-emerald-400/25">
              <CircleCheck className="size-4" aria-hidden />
            </span>
            <div className="grid gap-0.5">
              <p className="text-[13px] font-medium text-foreground">Aucune alerte</p>
              <p className="text-xs text-muted-foreground">
                Ingestion, conflits de mémoire et contenus sensibles sont sous contrôle.
              </p>
            </div>
          </div>
        ) : (
          <ul className="grid gap-2">
            {sorted.map((alert, i) => {
              const meta = ALERT_LEVEL_META[alert.level] ?? ALERT_LEVEL_META.info;
              const t = toneClasses(meta.tone);
              const link = alertLink(slug, alert.message);
              return (
                <li
                  key={`${alert.level}-${i}`}
                  className={cn("flex items-start gap-3 rounded-lg border px-3 py-2.5 text-[13px]", t.callout)}
                >
                  <span className="mt-px flex shrink-0 [&_svg]:size-4">{LEVEL_ICONS[alert.level] ?? LEVEL_ICONS.info}</span>
                  <div className="grid min-w-0 flex-1 gap-1">
                    <p className="leading-snug">
                      <span className="sr-only">{meta.label} : </span>
                      {alert.message}
                    </p>
                    {link ? (
                      <Link
                        href={link.href}
                        className="inline-flex w-fit items-center gap-1 rounded text-xs font-medium underline-offset-2 opacity-90 hover:underline hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        {link.label}
                        <ArrowRight className="size-3" aria-hidden />
                      </Link>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
