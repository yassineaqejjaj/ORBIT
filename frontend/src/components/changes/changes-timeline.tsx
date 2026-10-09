"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { projectHref } from "@/components/layout/nav";
import type { ChangeEvent } from "@/lib/api/features-feed";
import { formatDateLong, formatTime, toDate } from "@/lib/format";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";
import { changeMeta } from "./change-meta";

function dayKey(value: string): string {
  const date = toDate(value);
  if (!date) return "";
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function dayLabel(value: string): string {
  const date = toDate(value);
  if (!date) return "";
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (dayKey(date.toISOString()) === dayKey(today.toISOString())) return "Aujourd'hui";
  if (dayKey(date.toISOString()) === dayKey(yesterday.toISOString())) return "Hier";
  return formatDateLong(date);
}

/** Link to the screen where the change target can be inspected (when the target still exists). */
export function changeHref(slug: string, event: ChangeEvent): string | null {
  if (!event.target_id) return null;
  if (event.type === "memory.forgotten" || event.type === "document.forgotten") return null;
  if (event.target_type === "memory") return `${projectHref(slug, "memory")}?item=${encodeURIComponent(event.target_id)}`;
  if (event.target_type === "document") return `${projectHref(slug, "sources")}/${encodeURIComponent(event.target_id)}`;
  if (event.target_type === "snapshot") {
    const name = typeof event.data.name === "string" ? event.data.name : null;
    const version = typeof event.data.version === "number" ? `?v=${event.data.version}` : "";
    return name ? `${projectHref(slug, "snapshots")}/${encodeURIComponent(name)}${version}` : projectHref(slug, "snapshots");
  }
  if (event.target_type === "connector") return projectHref(slug, "connectors");
  return null;
}

/** `context.served`: coalesced counter (« 12 contextes servis à Agent Produit ») and counts only, never content. */
function servedText(event: ChangeEvent): { title: string; summary: string } {
  const d = event.data;
  const count = typeof d.count === "number" ? d.count : 1;
  const agent = typeof d.agent_name === "string" && d.agent_name ? d.agent_name : "l'Explorateur";
  const n = (key: string) => (typeof d[key] === "number" ? (d[key] as number) : 0);
  const last = `${n("included_count")} retenus, ${n("excluded_count")} exclus, ${n("tokens_used")} tokens`;
  return count > 1
    ? { title: `${count} contextes servis à ${agent}`, summary: `Dernier : ${last}` }
    : { title: `Contexte servi à ${agent}`, summary: last };
}

export function ChangeRow({ slug, event, compact }: { slug: string; event: ChangeEvent; compact?: boolean }) {
  const meta = changeMeta(event.type);
  const Icon = meta.icon;
  const tone = toneClasses(meta.tone);
  const href = changeHref(slug, event);
  const served = event.type === "context.served" ? servedText(event) : null;
  const title = served?.title ?? event.title;
  const summary = served?.summary ?? event.summary;
  return (
    <li className="relative flex gap-3 pb-4 last:pb-0">
      <span
        className={cn("relative z-[1] flex size-7 shrink-0 items-center justify-center rounded-full ring-4 ring-background", tone.soft)}
        aria-hidden
      >
        <Icon className="size-3.5" />
      </span>
      <div className="grid min-w-0 flex-1 gap-0.5 pt-0.5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className={cn("text-[11px] font-semibold uppercase tracking-wide", tone.text)}>{meta.label}</span>
          {event.classification >= 2 ? <ClassificationBadge level={event.classification} showLabel={false} /> : null}
          <time className="ml-auto text-[11px] tabular-nums text-muted-foreground" dateTime={event.created_at}>
            {formatTime(event.created_at)}
          </time>
        </div>
        {href ? (
          <Link
            href={href}
            className="group inline-flex w-fit max-w-full items-center gap-1 text-[13px] font-medium text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="truncate">{title}</span>
            <ArrowUpRight className="size-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
          </Link>
        ) : (
          <p className="truncate text-[13px] font-medium text-foreground">{title}</p>
        )}
        {!compact && summary ? <p className="text-xs leading-relaxed text-muted-foreground">{summary}</p> : null}
      </div>
    </li>
  );
}

/** Day-grouped vertical timeline. */
export function ChangesTimeline({ slug, events }: { slug: string; events: readonly ChangeEvent[] }) {
  const groups = React.useMemo(() => {
    const result: { key: string; label: string; items: ChangeEvent[] }[] = [];
    for (const event of events) {
      const key = dayKey(event.created_at);
      const last = result[result.length - 1];
      if (last && last.key === key) last.items.push(event);
      else result.push({ key, label: dayLabel(event.created_at), items: [event] });
    }
    return result;
  }, [events]);

  return (
    <div className="grid gap-6">
      {groups.map((group) => (
        <section key={group.key} aria-label={group.label} className="grid gap-3">
          <h2 className="sticky top-0 z-[2] -mx-1 bg-background/95 px-1 py-1 text-xs font-semibold capitalize text-muted-foreground backdrop-blur">
            {group.label}
          </h2>
          <ol className="relative grid before:absolute before:bottom-2 before:left-[13px] before:top-2 before:w-px before:bg-border">
            {group.items.map((event) => (
              <ChangeRow key={event.id} slug={slug} event={event} />
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}
