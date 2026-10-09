"use client";

import Link from "next/link";
import { ArrowRight, History } from "lucide-react";

import { projectHref } from "@/components/layout/nav";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AuditEvent, Member } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { ActivityTimeline } from "./activity-timeline";

const MAX_EVENTS = 4;
/** Session noise that says nothing about the project (still in the audit log). */
const HIDDEN_DOMAINS = new Set(["auth"]);

/** Level 3 — what happened recently, in product language; technical details stay in the audit log. */
export function RecentActivity({
  slug,
  events,
  members,
  className,
}: {
  slug: string;
  events: readonly AuditEvent[];
  members?: readonly Member[];
  className?: string;
}) {
  const visible = events.filter((event) => !HIDDEN_DOMAINS.has(event.action.split(".")[0] ?? "")).slice(0, MAX_EVENTS);
  return (
    <Card className={cn("flex flex-col", className)}>
      <CardHeader className="flex-row items-center gap-2">
        <History className="size-4 text-muted-foreground" aria-hidden />
        <CardTitle>Activité récente</CardTitle>
      </CardHeader>
      <CardContent className="flex-1">
        <ActivityTimeline slug={slug} events={visible} members={members} quiet />
      </CardContent>
      <div className="border-t border-border px-5 py-3">
        <Link
          href={`${projectHref(slug, "settings")}?tab=audit`}
          className="inline-flex items-center gap-1 rounded text-xs font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Voir le journal d&apos;audit
          <ArrowRight className="size-3" aria-hidden />
        </Link>
      </div>
    </Card>
  );
}
