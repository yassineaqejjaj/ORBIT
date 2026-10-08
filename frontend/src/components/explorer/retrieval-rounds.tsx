import { CircleCheck, CircleDashed, Repeat } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { RetrievalQueryKind, RetrievalRound } from "@/lib/api/types";
import { formatMs } from "@/lib/format";
import type { AnyTone } from "@/lib/tones";
import { cn } from "@/lib/utils";

const QUERY_KIND: Record<string, { label: string; tone: AnyTone; hint: string }> = {
  task: { label: "Tâche", tone: "neutral", hint: "Requête d'origine" },
  multi: { label: "Reformulation", tone: "violet", hint: "Reformulation proposée par le LLM (multi-requêtes)" },
  hyde: { label: "HyDE", tone: "pink", hint: "Réponse hypothétique recherchée comme un document" },
  expansion: { label: "Expansion", tone: "sky", hint: "Synonymes et entités du projet ajoutés à la requête" },
  subtopic: { label: "Sous-sujet", tone: "amber", hint: "Recherche ciblée d'un sous-sujet non couvert" },
};

function kindMeta(kind: RetrievalQueryKind) {
  return QUERY_KIND[kind] ?? { label: kind, tone: "neutral" as AnyTone, hint: kind };
}

export interface RetrievalRoundsProps {
  rounds: RetrievalRound[] | null | undefined;
  className?: string;
}

/** Iterative retrieval trace (AI_CONTEXT_ENGINEERING §B3–B4): queries of each round, new items, uncovered sub-topics. */
export function RetrievalRounds({ rounds, className }: RetrievalRoundsProps) {
  const last = rounds?.[rounds.length - 1];
  if (!rounds || !last) return null;
  return (
    <section className={cn("grid gap-2", className)} aria-label="Tours de recherche">
      <h3 className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
        <Repeat className="size-3.5 text-primary" aria-hidden />
        Recherche en {rounds.length} tour{rounds.length > 1 ? "s" : ""}
        <span className="font-normal text-muted-foreground">
          · {last.uncovered.length === 0 ? "tous les sous-sujets couverts" : `${last.uncovered.length} sous-sujet(s) non couvert(s)`}
        </span>
      </h3>
      <ol className="grid gap-2">
        {rounds.map((r) => (
          <li key={r.round} className="grid gap-1.5 rounded-md border border-border bg-muted/30 p-2.5 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium text-foreground">Tour {r.round}</span>
              <span className="tabular-nums text-muted-foreground">
                {r.new_items} élément{r.new_items > 1 ? "s" : ""} {r.round === 1 ? "trouvé" : "nouveau"}
                {r.new_items > 1 ? "s" : ""} · {formatMs(r.ms)}
              </span>
            </div>
            <ul className="grid gap-1">
              {r.queries.map((q, i) => {
                const meta = kindMeta(q.kind);
                return (
                  <li key={`${r.round}-${i}`} className="flex min-w-0 items-start gap-2">
                    <Badge tone={meta.tone} title={meta.hint} className="shrink-0">
                      {meta.label}
                    </Badge>
                    <span className="min-w-0 break-words text-muted-foreground">{q.text}</span>
                  </li>
                );
              })}
            </ul>
            {r.uncovered.length > 0 ? (
              <p className="flex items-start gap-1.5 text-muted-foreground">
                <CircleDashed className="mt-0.5 size-3.5 shrink-0 text-amber-600" aria-hidden />
                <span>Non couvert : {r.uncovered.join(" · ")}</span>
              </p>
            ) : (
              <p className="flex items-center gap-1.5 text-muted-foreground">
                <CircleCheck className="size-3.5 text-emerald-600" aria-hidden />
                Couverture complète
              </p>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
