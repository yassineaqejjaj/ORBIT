"use client";

import { Gavel, Lightbulb, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { MemoryCardFields as CardFields } from "@/lib/api/features-ask";
import type { MemoryItem } from "@/lib/api/types";

export const LLM_EXTRACTION_TAG = "extraction-llm";

export interface MemoryCardFieldsProps {
  item: MemoryItem & CardFields;
}

/** « Fiche » fields filled by the LLM-assisted extraction (F3): who decided, why, and how sure. */
export function MemoryCardFields({ item }: MemoryCardFieldsProps) {
  const fromLlm = item.tags.includes(LLM_EXTRACTION_TAG);
  if (!item.rationale && !item.decided_by && !item.confidence_reason && !fromLlm) return null;
  return (
    <section aria-label="Fiche mémoire" className="space-y-3 rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <h3 className="text-[13px] font-semibold">Fiche</h3>
        {fromLlm ? (
          <Badge tone="violet" title="Fiche proposée par l'extraction assistée par LLM, citation vérifiée dans la source">
            <Sparkles className="size-3" aria-hidden />
            Extraction LLM
          </Badge>
        ) : null}
      </div>
      <dl className="grid grid-cols-1 gap-3 text-[13px] sm:grid-cols-2">
        {item.decided_by ? (
          <div className="space-y-1">
            <dt className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <Gavel className="size-3.5" aria-hidden />
              Décidé par
            </dt>
            <dd>{item.decided_by}</dd>
          </div>
        ) : null}
        {item.rationale ? (
          <div className="space-y-1 sm:col-span-2">
            <dt className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <Lightbulb className="size-3.5" aria-hidden />
              Justification
            </dt>
            <dd className="leading-relaxed">{item.rationale}</dd>
          </div>
        ) : null}
        {item.confidence_reason ? (
          <div className="space-y-1 sm:col-span-2">
            <dt className="text-xs font-medium text-muted-foreground">Pourquoi ce niveau de confiance</dt>
            <dd className="leading-relaxed text-muted-foreground">{item.confidence_reason}</dd>
          </div>
        ) : null}
      </dl>
    </section>
  );
}
