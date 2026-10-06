import * as React from "react";

import { cn } from "@/lib/utils";

export interface PageHeaderProps {
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Small label above the title (e.g. section name). */
  eyebrow?: React.ReactNode;
  /** Lucide icon element shown in a tinted chip before the title. */
  icon?: React.ReactNode;
  /** Right-aligned actions (buttons). */
  actions?: React.ReactNode;
  /** Badges/meta rendered next to the title. */
  meta?: React.ReactNode;
  className?: string;
  /** Content below the header (tabs, filters). */
  children?: React.ReactNode;
}

export function PageHeader({ title, description, eyebrow, icon, actions, meta, className, children }: PageHeaderProps) {
  return (
    <header className={cn("flex flex-col gap-4 pb-6", className)}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          {icon ? (
            <span
              className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface text-brand shadow-panel [&_svg]:size-[18px]"
              aria-hidden
            >
              {icon}
            </span>
          ) : null}
          <div className="grid min-w-0 gap-1">
            {eyebrow ? (
              <p className="group-label">{eyebrow}</p>
            ) : null}
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <h1 className="truncate text-2xl font-semibold leading-tight tracking-[-0.02em] text-foreground sm:text-[28px]">{title}</h1>
              {meta}
            </div>
            {description ? (
              <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground text-balance">{description}</p>
            ) : null}
          </div>
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </header>
  );
}
