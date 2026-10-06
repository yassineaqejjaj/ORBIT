"use client";

import * as React from "react";

import { SimpleTooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export interface CitationBadgeProps {
  citation: string;
  /** Title of the cited item (tooltip). */
  title?: string;
  onClick?: (citation: string) => void;
  /** Highlighted (item currently focused). */
  active?: boolean;
  size?: "sm" | "md";
  className?: string;
}

/** `[S1]` citation marker. Interactive when `onClick` is provided (jumps to the retained item). */
export function CitationBadge({ citation, title, onClick, active, size = "sm", className }: CitationBadgeProps) {
  const classes = cn(
    "inline-flex shrink-0 items-center justify-center rounded-full font-mono font-semibold tabular-nums ring-1 ring-inset transition-colors",
    size === "sm" ? "h-5 min-w-7 px-1 text-[10.5px]" : "h-6 min-w-8 px-1.5 text-[11.5px]",
    active
      ? "bg-primary text-primary-foreground ring-transparent"
      : "bg-accent-soft text-accent-text ring-accent-coral/20",
    onClick && !active && "hover:bg-accent-coral/20",
    onClick && "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
    className,
  );
  const label = `[${citation}]`;
  if (!onClick) {
    return (
      <SimpleTooltip content={title} disabled={!title}>
        <span className={classes}>{label}</span>
      </SimpleTooltip>
    );
  }
  return (
    <SimpleTooltip content={title ? `${label} ${title}` : undefined} disabled={!title}>
      <button
        type="button"
        className={cn(classes, "align-baseline")}
        onClick={() => onClick(citation)}
        aria-label={title ? `Citation ${citation}\u00a0: ${title}` : `Citation ${citation}`}
      >
        {label}
      </button>
    </SimpleTooltip>
  );
}
