"use client";

import * as React from "react";
import { CircleCheck, CircleDashed, CircleMinus, CircleX, LoaderCircle } from "lucide-react";

import { SimpleTooltip } from "@/components/ui/tooltip";
import type { Job, JobStep } from "@/lib/api/types";
import { getMeta, JOB_STEP_META, JOB_STEP_NAMES, OPTIONAL_JOB_STEPS, type EnumMeta } from "@/lib/enums";
import { formatMs } from "@/lib/format";
import { cn } from "@/lib/utils";

export type StepDisplayStatus = "ok" | "failed" | "skipped" | "running" | "pending";

export interface DisplayStep {
  name: string;
  meta: EnumMeta;
  status: StepDisplayStatus;
  durationMs: number | null;
  detail: string | null;
  startedAt: string | null;
}

/** Job kinds that run the canonical ingestion pipeline (ARCHITECTURE §7). */
const PIPELINE_KINDS = new Set(["ingest", "reindex"]);

/**
 * Steps to display for a job: recorded steps first, then — for pipeline jobs still queued/running —
 * the remaining canonical steps as "running" (next one) and "pending".
 */
export function displaySteps(job: Pick<Job, "kind" | "status" | "steps">): DisplayStep[] {
  const recorded: DisplayStep[] = job.steps.map((s: JobStep) => ({
    name: s.name,
    meta: getMeta(JOB_STEP_META, s.name),
    status: s.status,
    durationMs: typeof s.duration_ms === "number" ? s.duration_ms : null,
    detail: s.detail ?? null,
    startedAt: s.started_at ?? null,
  }));
  const active = job.status === "queued" || job.status === "running";
  if (!active || !PIPELINE_KINDS.has(job.kind)) return recorded;
  const done = new Set(job.steps.map((s) => s.name));
  const remaining = JOB_STEP_NAMES.filter(
    (n) => !done.has(n) && !OPTIONAL_JOB_STEPS.has(n) && !(job.kind === "reindex" && n === "extract_memory"),
  );
  return [
    ...recorded,
    ...remaining.map<DisplayStep>((name, i) => ({
      name,
      meta: JOB_STEP_META[name],
      status: job.status === "running" && i === 0 ? "running" : "pending",
      durationMs: null,
      detail: null,
      startedAt: null,
    })),
  ];
}

const STATUS_LABEL: Record<StepDisplayStatus, string> = {
  ok: "Terminé",
  failed: "Échec",
  skipped: "Ignoré",
  running: "En cours",
  pending: "En attente",
};

export function StepStatusIcon({ status, className }: { status: StepDisplayStatus; className?: string }) {
  switch (status) {
    case "ok":
      return <CircleCheck className={cn("text-emerald-600 dark:text-emerald-400", className)} aria-hidden />;
    case "failed":
      return <CircleX className={cn("text-red-600 dark:text-red-400", className)} aria-hidden />;
    case "skipped":
      return <CircleMinus className={cn("text-slate-400 dark:text-slate-500", className)} aria-hidden />;
    case "running":
      return <LoaderCircle className={cn("animate-spin text-blue-600 dark:text-blue-400", className)} aria-hidden />;
    default:
      return <CircleDashed className={cn("text-subtle-foreground", className)} aria-hidden />;
  }
}

const CHIP_CLASSES: Record<StepDisplayStatus, string> = {
  ok: "bg-emerald-500 dark:bg-emerald-400",
  failed: "bg-red-500 dark:bg-red-400",
  skipped: "bg-slate-300 dark:bg-slate-600",
  running: "bg-blue-500 dark:bg-blue-400 animate-pulse",
  pending: "bg-transparent ring-1 ring-inset ring-border-strong",
};

/** Compact horizontal pipeline: one segment per step, colored by status, with a tooltip per step. */
export function JobStepsInline({ job, className }: { job: Pick<Job, "kind" | "status" | "steps">; className?: string }) {
  const steps = displaySteps(job);
  if (steps.length === 0) {
    return <span className={cn("text-xs text-subtle-foreground", className)}>{job.status === "queued" ? "En file" : "—"}</span>;
  }
  return (
    <span className={cn("inline-flex items-center gap-1", className)} aria-label={steps.map((s) => `${s.meta.label} : ${STATUS_LABEL[s.status]}`).join(", ")}>
      {steps.map((step, index) => (
        <SimpleTooltip
          key={`${step.name}-${index}`}
          content={
            <span className="grid gap-0.5">
              <span className="font-medium">
                {step.meta.label} · {STATUS_LABEL[step.status]}
              </span>
              {step.durationMs !== null ? <span className="opacity-80">{formatMs(step.durationMs)}</span> : null}
              {step.detail ? <span className="opacity-80">{step.detail}</span> : null}
            </span>
          }
        >
          <span className={cn("block h-2 w-5 rounded-full", CHIP_CLASSES[step.status])} />
        </SimpleTooltip>
      ))}
    </span>
  );
}

/** Total duration of a job (finished − started, else sum of step durations). */
export function jobDurationMs(job: Pick<Job, "started_at" | "finished_at" | "steps">): number | null {
  if (job.started_at && job.finished_at) {
    const ms = new Date(job.finished_at).getTime() - new Date(job.started_at).getTime();
    if (Number.isFinite(ms) && ms >= 0) return ms;
  }
  const sum = job.steps.reduce((acc, s) => acc + (typeof s.duration_ms === "number" ? s.duration_ms : 0), 0);
  return sum > 0 ? sum : null;
}

/** Vertical timeline of job steps with status icons, durations (proportional bars) and details. */
export function JobStepsTimeline({ job, className }: { job: Pick<Job, "kind" | "status" | "steps">; className?: string }) {
  const steps = displaySteps(job);
  const max = steps.reduce((m, s) => Math.max(m, s.durationMs ?? 0), 0);
  if (steps.length === 0) {
    return (
      <p className={cn("text-[13px] text-muted-foreground", className)}>
        {job.status === "queued" ? "Ce traitement est en file d'attente : il démarrera dès qu'un worker sera disponible." : "Aucune étape enregistrée."}
      </p>
    );
  }
  return (
    <ol className={cn("grid", className)}>
      {steps.map((step, index) => {
        const last = index === steps.length - 1;
        return (
          <li key={`${step.name}-${index}`} className="relative flex gap-3 pb-3 last:pb-0">
            {!last ? <span className="absolute left-[9px] top-6 bottom-0 w-px bg-border" aria-hidden /> : null}
            <span className="relative z-[1] mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-card">
              <StepStatusIcon status={step.status} className="size-[18px]" />
            </span>
            <div className="grid min-w-0 flex-1 gap-1">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span
                  className={cn(
                    "text-[13px] font-medium",
                    step.status === "pending" ? "text-muted-foreground" : "text-foreground",
                  )}
                >
                  {step.meta.label}
                </span>
                <span className="font-mono text-[11px] text-subtle-foreground">{step.name}</span>
                <span
                  className={cn(
                    "ml-auto text-xs tabular-nums",
                    step.status === "failed" ? "font-medium text-red-700 dark:text-red-300" : "text-muted-foreground",
                  )}
                >
                  {step.durationMs !== null ? formatMs(step.durationMs) : STATUS_LABEL[step.status]}
                </span>
              </div>
              {step.durationMs !== null && max > 0 ? (
                <span className="relative h-1 overflow-hidden rounded-full bg-muted" aria-hidden>
                  <span
                    className={cn(
                      "absolute inset-y-0 left-0 rounded-full",
                      step.status === "failed" ? "bg-red-500 dark:bg-red-400" : "bg-accent-coral",
                    )}
                    style={{ width: `${Math.max(2, (step.durationMs / max) * 100)}%` }}
                  />
                </span>
              ) : null}
              {step.detail ? (
                <p
                  className={cn(
                    "text-xs leading-relaxed",
                    step.status === "failed" ? "text-red-700 dark:text-red-300" : "text-muted-foreground",
                  )}
                >
                  {step.detail}
                </p>
              ) : step.meta.description && step.status !== "pending" ? (
                <p className="text-xs text-subtle-foreground">{step.meta.description}</p>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
