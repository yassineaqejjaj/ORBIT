"use client";

import * as React from "react";
import Link from "next/link";

import { OrbitMark } from "@/components/brand/orbit-logo";
import { projectHref } from "@/components/layout/nav";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useMeta, useProjectOverview } from "@/lib/api/hooks";
import { plural } from "@/lib/format";
import { cn } from "@/lib/utils";

export type PresenceState = "idle" | "working" | "waiting" | "offline";

export interface Presence {
  state: PresenceState;
  /** Status line, e.g. « ORBIT est opérationnel ». */
  label: string;
  /** Where the pill leads (sources while ingesting, review queue while waiting). */
  href?: string;
}

const ACTIVE_POLL_MS = 10_000;
const IDLE_POLL_MS = 60_000;

/**
 * ORBIT presence, from existing data only: project overview ingestion counters (queued + running jobs, which
 * include connector syncs) and the memory review count. Priority: offline › working › waiting › idle.
 */
export function usePresence(slug: string | undefined, inboxTotal: number | undefined): Presence {
  const meta = useMeta();
  const overview = useProjectOverview(slug ?? "", {
    refetchInterval: (query) => {
      const ing = query.state.data?.ingestion;
      return ing && ing.queued + ing.running > 0 ? ACTIVE_POLL_MS : IDLE_POLL_MS;
    },
  });
  if (meta.isError) return { state: "offline", label: "API injoignable" };
  const ingestion = slug ? overview.data?.ingestion : undefined;
  const busy = ingestion ? ingestion.queued + ingestion.running : 0;
  if (slug && busy > 0) {
    return {
      state: "working",
      label: `Ingestion en cours · ${plural(busy, "tâche")}`,
      href: projectHref(slug, "sources"),
    };
  }
  if (slug && inboxTotal) {
    return {
      state: "waiting",
      label: `${plural(inboxTotal, "élément")} à revoir`,
      href: projectHref(slug, "inbox"),
    };
  }
  return { state: "idle", label: "ORBIT est opérationnel" };
}

/** The ORBIT "o" ring, animated by presence state (static under prefers-reduced-motion). */
export function PresenceRing({ state, size = 22, className }: { state: PresenceState; size?: number; className?: string }) {
  return (
    <span
      className={cn("relative inline-flex shrink-0 items-center justify-center rounded-full", className)}
      style={{ width: size, height: size }}
      aria-hidden
    >
      {state === "working" ? (
        <span className="absolute -inset-1 rounded-full bg-glow blur-[6px] motion-safe:animate-breathe-fast" />
      ) : null}
      {state === "waiting" ? (
        <span className="absolute -inset-0.5 rounded-full motion-safe:animate-attention" />
      ) : null}
      <OrbitMark
        className={cn(
          "relative size-full",
          state === "idle" && "motion-safe:animate-breathe",
          state === "working" && "motion-safe:animate-orbit",
          state === "offline" && "opacity-40 grayscale",
        )}
        style={state === "working" ? { animationDuration: "2.4s" } : undefined}
      />
    </span>
  );
}

/** Sidebar presence pill: ring + status line (collapsed: ring only, label in a tooltip). */
export function PresencePill({
  presence,
  collapsed = false,
  onNavigate,
}: {
  presence: Presence;
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const { state, label, href } = presence;
  const content = (
    <>
      <PresenceRing state={state} size={collapsed ? 24 : 20} />
      <span
        className={cn(
          "min-w-0 truncate text-[12.5px] font-medium",
          collapsed && "sr-only",
          state === "working" && "text-shimmer text-muted-foreground",
          state === "waiting" && "text-foreground",
          state === "idle" && "text-muted-foreground",
          state === "offline" && "text-danger",
        )}
      >
        {label}
      </span>
      {!collapsed && state === "waiting" ? (
        <span className="ml-auto size-1.5 shrink-0 rounded-full bg-accent-coral" aria-hidden />
      ) : null}
    </>
  );
  const classes = cn(
    "flex items-center gap-2.5 rounded-full border border-sidebar-border bg-surface-2/60 transition-colors duration-150",
    collapsed ? "mx-auto size-10 justify-center p-0" : "h-9 w-full px-2.5",
    href && "hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
  );
  const node = href ? (
    <Link href={href} onClick={onNavigate} className={classes} aria-live="polite">
      {content}
    </Link>
  ) : (
    <div className={classes} role="status" aria-live="polite">
      {content}
    </div>
  );
  return collapsed ? (
    <SimpleTooltip content={label} side="right">
      {node}
    </SimpleTooltip>
  ) : (
    node
  );
}
