import * as React from "react";

import { cn } from "@/lib/utils";

export interface EmptyStateProps {
  /** Lucide icon element, e.g. <Inbox />. */
  icon?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Primary/secondary actions (buttons, links). */
  action?: React.ReactNode;
  /** "card" adds a dashed border container; "plain" has none. */
  variant?: "card" | "plain";
  size?: "sm" | "md" | "lg";
  className?: string;
  children?: React.ReactNode;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  variant = "card",
  size = "md",
  className,
  children,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center",
        variant === "card" && "rounded-xl border border-dashed border-border-strong bg-card/50",
        size === "sm" && "gap-2 px-4 py-8",
        size === "md" && "gap-3 px-6 py-12",
        size === "lg" && "gap-4 px-6 py-20",
        className,
      )}
    >
      {icon ? (
        <div
          className={cn(
            "relative flex items-center justify-center rounded-xl border border-border bg-background text-muted-foreground shadow-xs",
            size === "sm" ? "size-9 [&_svg]:size-4" : "size-11 [&_svg]:size-5",
          )}
          aria-hidden
        >
          <span className="absolute -inset-2 -z-10 rounded-2xl bg-brand/5" />
          {icon}
        </div>
      ) : null}
      <div className="grid max-w-md gap-1">
        <h3 className={cn("font-semibold tracking-tight text-foreground", size === "lg" ? "text-base" : "text-sm")}>
          {title}
        </h3>
        {description ? <p className="text-[13px] leading-relaxed text-muted-foreground">{description}</p> : null}
      </div>
      {action ? <div className="mt-1 flex flex-wrap items-center justify-center gap-2">{action}</div> : null}
      {children}
    </div>
  );
}
