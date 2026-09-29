"use client";

import * as React from "react";
import { Check, Loader2 } from "lucide-react";

import { CONTEXT_STAGES, CONTEXT_STAGE_META } from "@/lib/enums";
import { formatMs } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Cadence of the simulated progression (the API answers in one response, p95 < 1,5 s). */
const STEP_MS = 190;

export interface PipelineProgressProps {
  task: string;
  className?: string;
}

/**
 * Loading state of the explorer: the 8 assembly stages light up in order
 * (understand → retrieve → fuse → rerank → govern → select → compress → package) while the request runs.
 */
export function PipelineProgress({ task, className }: PipelineProgressProps) {
  const [active, setActive] = React.useState(0);
  const [elapsed, setElapsed] = React.useState(0);

  React.useEffect(() => {
    const started = performance.now();
    const step = window.setInterval(() => {
      setActive((i) => Math.min(i + 1, CONTEXT_STAGES.length - 1));
    }, STEP_MS);
    const clock = window.setInterval(() => setElapsed(performance.now() - started), 100);
    return () => {
      window.clearInterval(step);
      window.clearInterval(clock);
    };
  }, []);

  const current = CONTEXT_STAGES[active] ?? CONTEXT_STAGES[0];
  const meta = CONTEXT_STAGE_META[current];

  return (
    <section
      className={cn("overflow-hidden rounded-xl border border-border bg-card shadow-xs", className)}
      aria-live="polite"
      aria-busy="true"
      aria-label="Assemblage du contexte en cours"
    >
      <div className="relative h-1 overflow-hidden bg-muted" aria-hidden>
        <div className="absolute inset-y-0 w-1/3 animate-indeterminate rounded-full bg-primary" />
      </div>
      <div className="grid gap-5 p-5">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
          <div className="grid min-w-0 gap-1">
            <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-subtle-foreground">Assemblage en cours</p>
            <p className="line-clamp-2 text-sm font-medium text-foreground">{task}</p>
          </div>
          <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">{formatMs(elapsed)}</span>
        </div>

        <ol className="grid grid-cols-4 gap-x-2 gap-y-4 sm:grid-cols-8">
          {CONTEXT_STAGES.map((stage, i) => {
            const done = i < active;
            const running = i === active;
            return (
              <li key={stage} className="relative flex flex-col items-center gap-2 text-center">
                {i > 0 ? (
                  <span
                    className={cn(
                      "absolute right-1/2 top-4 hidden h-0.5 w-full -translate-y-1/2 sm:block",
                      i <= active ? "bg-primary/60" : "bg-border",
                    )}
                    aria-hidden
                  />
                ) : null}
                <span
                  className={cn(
                    "relative z-10 flex size-8 items-center justify-center rounded-full border text-xs font-semibold transition-colors duration-200",
                    done && "border-primary bg-primary text-primary-foreground",
                    running && "border-primary bg-brand-soft text-primary ring-4 ring-primary/15",
                    !done && !running && "border-border bg-background text-subtle-foreground",
                  )}
                  aria-hidden
                >
                  {done ? <Check className="size-4" /> : running ? <Loader2 className="size-4 animate-spin" /> : i + 1}
                </span>
                <span
                  className={cn(
                    "text-[11.5px] leading-tight",
                    running ? "font-semibold text-foreground" : done ? "text-foreground/80" : "text-subtle-foreground",
                  )}
                >
                  {CONTEXT_STAGE_META[stage].label}
                </span>
                <span className="sr-only">{done ? "terminée" : running ? "en cours" : "en attente"}</span>
              </li>
            );
          })}
        </ol>

        <p className="text-center text-[13px] text-muted-foreground">
          <span className="font-medium text-foreground">{meta.label}</span> — {meta.description}
        </p>
      </div>
    </section>
  );
}
