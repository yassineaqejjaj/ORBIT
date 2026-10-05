"use client";

import {
  BookOpenText,
  Building2,
  FolderSync,
  GitBranch,
  HardDrive,
  ListTodo,
  MessagesSquare,
  NotebookPen,
  Plug,
  Ticket,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { isRunActive, type ConnectorRun, type ConnectorType } from "@/lib/api/features-connectors";
import { formatMs, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { RUN_STATUS_META } from "./connector-meta";

/** Icons of the MCP presets (generic glyphs: no vendor logos). */
const MCP_ICONS: Record<string, LucideIcon> = {
  atlassian: BookOpenText,
  microsoft: Building2,
  google: HardDrive,
  slack: MessagesSquare,
  github: GitBranch,
  linear: ListTodo,
  obsidian: NotebookPen,
  plug: Plug,
};

/** Preset id → icon key (saved connectors only carry the preset id). */
const PRESET_ICONS: Record<string, string> = {
  atlassian: "atlassian",
  ms365: "microsoft",
  google_workspace: "google",
  slack: "slack",
  github: "github",
  linear: "linear",
  obsidian: "obsidian",
  custom: "plug",
};

export function ConnectorTypeIcon({
  type,
  icon,
  preset,
  className,
}: {
  type: ConnectorType;
  /** MCP: icon key from ``/connectors/types``. */
  icon?: string | null;
  /** MCP: preset id of a saved connector. */
  preset?: string | null;
  className?: string;
}) {
  const Icon =
    type === "mcp"
      ? (MCP_ICONS[icon ?? PRESET_ICONS[preset ?? ""] ?? "plug"] ?? Plug)
      : type === "jira"
        ? Ticket
        : type === "confluence"
          ? BookOpenText
          : FolderSync;
  return <Icon className={cn("size-4", className)} aria-hidden />;
}

/** « MCP » badge of the connectors served through a Model Context Protocol server (F6). */
export function McpBadge({ className }: { className?: string }) {
  return (
    <Badge tone="violet" size="sm" className={className} title="Connecteur via un serveur MCP (Model Context Protocol)">
      MCP
    </Badge>
  );
}

export function RunStatusBadge({ run }: { run: ConnectorRun }) {
  const meta = RUN_STATUS_META[run.status];
  return (
    <Badge tone={meta.tone} size="sm" dot pulse={isRunActive(run)}>
      {meta.label}
    </Badge>
  );
}

const STATS: { key: keyof ConnectorRun; label: string; tone?: string }[] = [
  { key: "fetched", label: "Récupérés" },
  { key: "created", label: "Créés", tone: "text-success" },
  { key: "updated", label: "Mis à jour", tone: "text-info" },
  { key: "unchanged", label: "Inchangés" },
  { key: "forgotten", label: "Oubliés", tone: "text-warning" },
  { key: "errors", label: "Erreurs", tone: "text-destructive" },
];

/** Compact grid of the run counters. */
export function RunCounters({ run, className }: { run: ConnectorRun; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-3 gap-2 sm:grid-cols-6", className)}>
      {STATS.map((stat) => {
        const value = Number(run[stat.key] ?? 0);
        return (
          <div key={stat.key} className="rounded-md border border-border bg-muted/40 px-2.5 py-2">
            <dt className="text-[11px] text-muted-foreground">{stat.label}</dt>
            <dd className={cn("text-base font-semibold tabular-nums", value > 0 && stat.tone)}>{formatNumber(value, 0)}</dd>
          </div>
        );
      })}
    </dl>
  );
}

/** Live progress of a run: indeterminate bar while active, message and counters. */
export function RunProgress({ run }: { run: ConnectorRun }) {
  const active = isRunActive(run);
  const tone = run.status === "failed" ? "red" : run.status === "partial" ? "amber" : active ? "blue" : "green";
  return (
    <div className="grid gap-3" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <RunStatusBadge run={run} />
        <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
          {run.error ?? run.progress?.message ?? (active ? "Synchronisation en cours…" : "Terminée")}
        </span>
        {run.duration_ms != null ? <span className="text-xs text-muted-foreground">{formatMs(run.duration_ms)}</span> : null}
      </div>
      <Progress value={active ? null : 100} tone={tone} size="sm" aria-label="Progression de la synchronisation" />
      <RunCounters run={run} />
      {run.error_samples.length > 0 ? (
        <details className="rounded-md border border-border px-3 py-2 text-xs">
          <summary className="cursor-pointer font-medium">
            {run.error_samples.length} élément(s) en erreur
          </summary>
          <ul className="mt-2 grid gap-1 text-muted-foreground">
            {run.error_samples.map((sample, index) => (
              <li key={`${sample.item}-${index}`}>
                <span className="font-medium text-foreground">{sample.item}</span> — {sample.error}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
