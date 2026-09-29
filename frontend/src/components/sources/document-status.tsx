"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { DOCUMENT_STATUS_META, getMeta, type DocumentStatus } from "@/lib/enums";

export const ACTIVE_DOCUMENT_STATUSES: ReadonlySet<string> = new Set(["pending", "processing"]);

export function isDocumentActive(status: DocumentStatus | string): boolean {
  return ACTIVE_DOCUMENT_STATUSES.has(status);
}

/** Document status pill; the tooltip explains the status and shows `status_reason` (failure cause…). */
export function DocumentStatusBadge({
  status,
  reason,
  size = "sm",
}: {
  status: DocumentStatus;
  reason?: string | null;
  size?: "sm" | "md";
}) {
  const meta = getMeta(DOCUMENT_STATUS_META, status);
  const active = status === "processing";
  return (
    <SimpleTooltip
      content={
        <span className="grid gap-0.5">
          <span className="font-medium">{meta.label}</span>
          {meta.description ? <span className="opacity-80">{meta.description}</span> : null}
          {reason ? <span className="mt-0.5 opacity-90">Motif : {reason}</span> : null}
        </span>
      }
    >
      <span className="inline-flex" tabIndex={0} aria-label={reason ? `${meta.label} — ${reason}` : meta.label}>
        <Badge tone={meta.tone} size={size} dot={!active} pulse={active}>
          {meta.label}
        </Badge>
      </span>
    </SimpleTooltip>
  );
}
