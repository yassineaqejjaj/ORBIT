"use client";

import * as React from "react";
import { Bot, ChevronRight, EyeOff, Layers, ShieldCheck } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { StatusBadge } from "@/components/domain/status-badge";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type { ChunkView } from "@/lib/api/types";
import { getMeta, PII_TYPE_META, type PiiType } from "@/lib/enums";
import { formatNumber, formatTokens, plural } from "@/lib/format";
import { cn } from "@/lib/utils";
import { PiiHighlightedText, RedactedText } from "./pii-text";

const PAGE = 20;

function sectionParts(section: string | null): string[] {
  if (!section) return [];
  return section
    .split(/\s*(?:>|›|»|\/|\|)\s*/)
    .map((p) => p.trim())
    .filter(Boolean);
}

function piiCounts(chunk: ChunkView): Array<[PiiType, number]> {
  const counts = new Map<PiiType, number>();
  for (const e of chunk.pii) counts.set(e.type, (counts.get(e.type) ?? 0) + 1);
  return [...counts.entries()];
}

function ChunkCard({ chunk, redacted, canSeeOriginal }: { chunk: ChunkView; redacted: boolean; canSeeOriginal: boolean }) {
  const parts = sectionParts(chunk.section);
  const pii = piiCounts(chunk);
  const showOriginal = canSeeOriginal && !redacted;
  return (
    <article
      className={cn(
        "grid gap-2.5 rounded-lg border border-border bg-card px-4 py-3 shadow-xs",
        chunk.status !== "active" && "border-dashed opacity-80",
      )}
      aria-label={`Extrait ${chunk.ordinal + 1}`}
    >
      <header className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] font-medium tabular-nums text-muted-foreground">
          #{chunk.ordinal + 1}
        </span>
        {parts.length > 0 ? (
          <nav aria-label="Section" className="flex min-w-0 flex-wrap items-center gap-0.5 text-xs text-muted-foreground">
            {parts.map((p, i) => (
              <React.Fragment key={`${p}-${i}`}>
                {i > 0 ? <ChevronRight className="size-3 shrink-0 text-subtle-foreground" aria-hidden /> : null}
                <span className={cn("truncate", i === parts.length - 1 && "font-medium text-foreground")}>{p}</span>
              </React.Fragment>
            ))}
          </nav>
        ) : (
          <span className="text-xs text-subtle-foreground">Sans section</span>
        )}
        <span className="ml-auto flex flex-wrap items-center gap-1.5">
          {pii.map(([type, count]) => (
            <Badge key={type} tone="pink" size="sm" title="Données personnelles détectées">
              {getMeta(PII_TYPE_META, type).label}
              {count > 1 ? ` ×${count}` : ""}
            </Badge>
          ))}
          {chunk.classification >= 2 ? <ClassificationBadge level={chunk.classification} showLabel={false} /> : null}
          {chunk.status !== "active" ? <StatusBadge kind="chunk" status={chunk.status} /> : null}
          {chunk.quarantined ? (
            <Badge
              tone="danger"
              size="sm"
              title={(chunk.injection_reasons ?? []).map((r) => r.label).join(" · ") || "Injection de prompt suspectée"}
            >
              Quarantaine
            </Badge>
          ) : null}
          <span className="text-xs tabular-nums text-muted-foreground">{formatTokens(chunk.token_count)}</span>
        </span>
      </header>
      <div className="text-[13px] leading-relaxed text-foreground">
        {showOriginal ? (
          chunk.pii.length > 0 ? (
            <PiiHighlightedText text={chunk.text} pii={chunk.pii} />
          ) : (
            <p className="whitespace-pre-wrap break-words">{chunk.text}</p>
          )
        ) : (
          <RedactedText text={chunk.text_redacted || chunk.text} />
        )}
      </div>
    </article>
  );
}

export interface ChunkListProps {
  chunks: readonly ChunkView[];
  version: number;
  /** Editors see the original text with PII highlighted; others only the redacted text. */
  canSeeOriginal: boolean;
}

/** "Contenu" tab: chunks of the current version, PII highlighted inline, with the agent (redacted) view toggle. */
export function ChunkList({ chunks, version, canSeeOriginal }: ChunkListProps) {
  const [agentView, setAgentView] = React.useState(!canSeeOriginal);
  const [piiOnly, setPiiOnly] = React.useState(false);
  const [limit, setLimit] = React.useState(PAGE);

  const sorted = React.useMemo(() => [...chunks].sort((a, b) => a.ordinal - b.ordinal), [chunks]);
  const withPii = sorted.filter((c) => c.pii.length > 0);
  const visible = piiOnly ? withPii : sorted;
  const totalTokens = sorted.reduce((acc, c) => acc + c.token_count, 0);
  const piiTotal = withPii.reduce((acc, c) => acc + c.pii.length, 0);
  const redacted = agentView || !canSeeOriginal;

  if (sorted.length === 0) {
    return (
      <EmptyState
        icon={<Layers />}
        title="Aucun extrait"
        description="Le document n'a pas encore été découpé : les extraits apparaîtront à la fin du traitement."
      />
    );
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3 rounded-lg border border-border bg-muted/30 px-4 py-2.5">
        <p className="text-xs text-muted-foreground">
          <span className="font-medium text-foreground">{plural(sorted.length, "extrait")}</span> · version {version} ·{" "}
          {formatTokens(totalTokens)}
          {piiTotal > 0 ? (
            <>
              {" · "}
              <span className="font-medium text-pink-700 dark:text-pink-300">
                {plural(piiTotal, "donnée personnelle", "données personnelles")}
              </span>
            </>
          ) : null}
        </p>
        <div className="ml-auto flex flex-wrap items-center gap-x-5 gap-y-2">
          {withPii.length > 0 ? (
            <div className="flex items-center gap-2">
              <Switch id="chunks-pii-only" size="sm" checked={piiOnly} onCheckedChange={setPiiOnly} />
              <Label htmlFor="chunks-pii-only" className="text-xs font-normal">
                Uniquement avec données personnelles ({formatNumber(withPii.length, 0)})
              </Label>
            </div>
          ) : null}
          {canSeeOriginal ? (
            <div className="flex items-center gap-2">
              <Switch id="chunks-agent-view" size="sm" checked={agentView} onCheckedChange={setAgentView} />
              <Label htmlFor="chunks-agent-view" className="flex items-center gap-1.5 text-xs font-normal">
                <Bot className="size-3.5" aria-hidden />
                Vue agent (caviardée)
              </Label>
            </div>
          ) : null}
        </div>
      </div>

      {redacted ? (
        <Alert tone="neutral" icon={<EyeOff aria-hidden />}>
          {canSeeOriginal
            ? "Vue agent : c'est exactement le texte servi aux agents, données personnelles remplacées par des marqueurs ([EMAIL], [TÉLÉPHONE]…)."
            : "Vous voyez la version caviardée servie aux agents. Le texte original est réservé aux éditeurs du projet."}
        </Alert>
      ) : piiTotal > 0 ? (
        <Alert tone="violet" icon={<ShieldCheck aria-hidden />}>
          Données personnelles <mark className="rounded-[3px] bg-pink-100 px-0.5 text-pink-950 dark:bg-pink-400/20 dark:text-pink-100">surlignées</mark> :
          visibles des éditeurs uniquement, elles sont systématiquement caviardées dans le contexte servi aux agents.
        </Alert>
      ) : null}

      <div className="grid gap-2.5">
        {visible.slice(0, limit).map((chunk) => (
          <ChunkCard key={chunk.id} chunk={chunk} redacted={redacted} canSeeOriginal={canSeeOriginal} />
        ))}
      </div>
      {visible.length > limit ? (
        <div className="flex justify-center">
          <Button variant="secondary" size="sm" onClick={() => setLimit((l) => l + PAGE)}>
            Afficher {Math.min(PAGE, visible.length - limit)} extraits de plus ({formatNumber(visible.length - limit, 0)} restants)
          </Button>
        </div>
      ) : null}
    </div>
  );
}
