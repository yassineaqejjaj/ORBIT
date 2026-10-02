"use client";

import * as React from "react";
import Link from "next/link";
import { History } from "lucide-react";

import { RelativeTime } from "@/components/domain/relative-time";
import { projectHref } from "@/components/layout/nav";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import type { AuditEvent, Member } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { ActorAvatar } from "./actor-avatar";
import { auditActionMeta } from "./audit-meta";

export interface ActivityTimelineProps {
  slug: string;
  events: readonly AuditEvent[];
  members?: readonly Member[];
  className?: string;
  /** Dashboard: keep only semantic colors (red failures, green successes), neutral otherwise. */
  quiet?: boolean;
}

/** Link to the screen showing the audit target, when there is one. */
export function auditTargetHref(slug: string, event: Pick<AuditEvent, "target_type" | "target_id" | "action">): string | null {
  if (!event.target_id) return null;
  if (event.action === "document.forget") return `${projectHref(slug, "sources")}/${encodeURIComponent(event.target_id)}`;
  switch (event.target_type) {
    case "document":
      return `${projectHref(slug, "sources")}/${encodeURIComponent(event.target_id)}`;
    case "memory":
      return `${projectHref(slug, "memory")}?item=${encodeURIComponent(event.target_id)}`;
    case "agent":
      return `${projectHref(slug, "settings")}?tab=agents`;
    case "user":
    case "member":
      return `${projectHref(slug, "settings")}?tab=members`;
    case "source":
      return `${projectHref(slug, "sources")}?tab=sources`;
    case "snapshot": {
      // Snapshot targets are "<name>@v<version>" (not UUIDs).
      const match = /^(.+)@v(\d+)$/.exec(event.target_id);
      const name = match?.[1] ?? event.target_id;
      const version = match?.[2] ? `?v=${match[2]}` : "";
      return `${projectHref(slug, "snapshots")}/${encodeURIComponent(name)}${version}`;
    }
    default:
      return null;
  }
}

/** Vertical timeline of recent audit events: actor avatar, action, French summary, relative time. */
export function ActivityTimeline({ slug, events, members, className, quiet = false }: ActivityTimelineProps) {
  if (events.length === 0) {
    return (
      <EmptyState
        size="sm"
        variant="plain"
        icon={<History />}
        title="Aucune activité récente"
        description="Les ingestions, validations de mémoire, contextes servis et changements de droits apparaîtront ici."
      />
    );
  }
  return (
    <ol className={cn("relative grid gap-0", className)} aria-label="Activité récente">
      {events.map((event, index) => {
        const meta = auditActionMeta(event.action);
        const href = auditTargetHref(slug, event);
        const last = index === events.length - 1;
        return (
          <li key={event.id} className="relative flex gap-3 pb-4 last:pb-0">
            {!last ? <span className="absolute left-4 top-9 bottom-0 w-px bg-border" aria-hidden /> : null}
            <ActorAvatar actorType={event.actor_type} actorId={event.actor_id} label={event.actor_label} members={members} />
            <div className="grid min-w-0 flex-1 gap-1 pt-0.5">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="truncate text-[13px] font-medium text-foreground">{event.actor_label}</span>
                <Badge
                  tone={quiet ? (meta.tone === "red" || meta.tone === "green" ? meta.tone : "neutral") : meta.tone}
                  size="sm"
                  title={event.action}
                >
                  {meta.label}
                </Badge>
                <RelativeTime date={event.created_at} className="ml-auto text-xs text-muted-foreground" />
              </div>
              {event.summary ? (
                href ? (
                  <Link
                    href={href}
                    className="line-clamp-2 rounded text-[13px] leading-snug text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {event.summary}
                  </Link>
                ) : (
                  <p className="line-clamp-2 text-[13px] leading-snug text-muted-foreground">{event.summary}</p>
                )
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
