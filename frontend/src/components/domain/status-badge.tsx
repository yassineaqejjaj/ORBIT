import { Badge } from "@/components/ui/badge";
import {
  CHUNK_STATUS_META,
  DOCUMENT_STATUS_META,
  getMeta,
  JOB_STATUS_META,
  JOB_STEP_STATUS_META,
  MEMORY_STATUS_META,
  type EnumMeta,
} from "@/lib/enums";

export type StatusKind = "document" | "job" | "memory" | "chunk" | "step";

const METAS = {
  document: DOCUMENT_STATUS_META,
  job: JOB_STATUS_META,
  memory: MEMORY_STATUS_META,
  chunk: CHUNK_STATUS_META,
  step: JOB_STEP_STATUS_META,
} as const;

const ACTIVE = new Set(["processing", "running"]);

export interface StatusBadgeProps {
  /** Which status family. */
  kind: StatusKind;
  status: string;
  size?: "sm" | "md";
  className?: string;
}

/** Status pill for documents, jobs, memory items, chunks and pipeline steps (FR labels, pulsing when active). */
export function StatusBadge({ kind, status, size = "sm", className }: StatusBadgeProps) {
  const meta = getMeta(METAS[kind] as Record<string, EnumMeta>, status);
  const active = ACTIVE.has(status);
  return (
    <Badge
      tone={meta.tone}
      size={size}
      dot={!active}
      pulse={active}
      className={className}
      title={meta.description}
    >
      {meta.label}
    </Badge>
  );
}
