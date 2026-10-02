"use client";

import * as React from "react";

import { ContextItemCard } from "@/components/explorer/context-item-card";
import { EmptyState } from "@/components/ui/empty-state";
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import type { ContextItem } from "@/lib/api/types";

export interface SourcesSheetProps {
  slug: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  citations: ContextItem[];
  active: string | null;
}

/** Side panel listing the governed sources of an answer; the clicked citation is highlighted. */
export function SourcesSheet({ slug, open, onOpenChange, citations, active }: SourcesSheetProps) {
  const bm25Max = Math.max(0, ...citations.map((c) => c.scores.bm25 ?? 0));
  React.useEffect(() => {
    if (!open || !active) return;
    const id = window.setTimeout(() => {
      document.getElementById(`ask-source-${active}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(id);
  }, [open, active]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" size="lg">
        <SheetHeader>
          <SheetTitle>Sources de la réponse</SheetTitle>
          <SheetDescription>
            Extraits servis par le moteur de contexte, filtrés selon vos droits et votre habilitation.
          </SheetDescription>
        </SheetHeader>
        <SheetBody className="space-y-3">
          {citations.length === 0 ? (
            <EmptyState title="Aucune source citée" description="Cette réponse ne s'appuie sur aucune source." size="sm" />
          ) : (
            citations.map((item) => (
              <div key={item.citation} id={`ask-source-${item.citation}`}>
                <ContextItemCard item={item} slug={slug} bm25Max={bm25Max} highlighted={item.citation === active} />
              </div>
            ))
          )}
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}
