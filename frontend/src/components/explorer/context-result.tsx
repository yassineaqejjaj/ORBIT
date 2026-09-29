"use client";

import * as React from "react";
import { Ban, CheckCircle2, FileText, Inbox, MessageSquareHeart, Timer } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMediaQuery } from "@/hooks/use-media-query";
import type { ContextFeedback, ContextPackage } from "@/lib/api/types";
import {
  bm25Scale,
  citationDomId,
  citationTitles as buildCitationTitles,
  contextFilename,
  exclusionGroupDomId,
  exclusionSummaryEntries,
  groupExclusions,
} from "@/lib/explorer-utils";
import { formatMs, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AssembledContext } from "./assembled-context";
import { ContextItemCard } from "./context-item-card";
import { ExcludedList } from "./excluded-list";
import { ExclusionSummary } from "./exclusion-summary";
import { FeedbackWidget } from "./feedback-widget";
import { ResultSummary, type ResultActor } from "./result-summary";
import { StageWaterfall } from "./stage-waterfall";

type ColumnKey = "retained" | "excluded" | "context";

export interface ContextResultProps {
  pkg: ContextPackage;
  slug: string;
  feedback?: ContextFeedback[];
  actor?: ResultActor | null;
  /** Relevance threshold of the project (drawn on score bars). */
  minRelevance?: number;
  onReuse?: () => void;
}

const HIGHLIGHT_MS = 2400;

function ColumnHeader({ icon, title, count, description }: { icon: React.ReactNode; title: string; count?: number; description: string }) {
  return (
    <CardHeader className="gap-0.5 border-b border-border px-4 py-3">
      <CardTitle className="flex items-center gap-2 [&_svg]:size-4">
        {icon}
        {title}
        {typeof count === "number" ? (
          <span className="rounded-md bg-muted px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-muted-foreground">
            {formatNumber(count, 0)}
          </span>
        ) : null}
      </CardTitle>
      <CardDescription className="text-xs">{description}</CardDescription>
    </CardHeader>
  );
}

/** Full explanation of one assembled context: summary, stage waterfall, retained / excluded / served Markdown, feedback. */
export function ContextResult({ pkg, slug, feedback, actor, minRelevance, onReuse }: ContextResultProps) {
  const isDesktop = useMediaQuery("(min-width: 1280px)");
  const [tab, setTab] = React.useState<ColumnKey>("retained");
  const [highlighted, setHighlighted] = React.useState<string | null>(null);
  const [focusedGroup, setFocusedGroup] = React.useState<string | null>(null);
  const pendingScroll = React.useRef<string | null>(null);
  // Forces a commit even when the highlighted value does not change (clicking the same citation twice).
  const [, requestScroll] = React.useReducer((x: number) => x + 1, 0);

  const titles = React.useMemo(() => buildCitationTitles(pkg.items), [pkg.items]);
  const groups = React.useMemo(() => groupExclusions(pkg.excluded, pkg.exclusion_summary), [pkg.excluded, pkg.exclusion_summary]);
  const summaryEntries = React.useMemo(
    () => exclusionSummaryEntries(pkg.exclusion_summary, pkg.excluded),
    [pkg.exclusion_summary, pkg.excluded],
  );
  const excludedTotal = groups.reduce((acc, g) => acc + g.count, 0);
  const bm25Max = React.useMemo(() => bm25Scale(pkg.items), [pkg.items]);
  const filename = contextFilename(slug, pkg.request_id, pkg.snapshot);

  // Clear transient highlights when another package is displayed.
  const [prevId, setPrevId] = React.useState(pkg.request_id);
  if (prevId !== pkg.request_id) {
    setPrevId(pkg.request_id);
    setHighlighted(null);
    setFocusedGroup(null);
  }

  // Scroll to the requested element once it is rendered (tab switches render it on the next commit).
  React.useEffect(() => {
    const target = pendingScroll.current;
    if (!target) return;
    const el = document.getElementById(target);
    if (!el) return;
    pendingScroll.current = null;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
    if (el.tagName === "ARTICLE") el.focus({ preventScroll: true });
  });

  React.useEffect(() => {
    if (!highlighted) return;
    const t = window.setTimeout(() => setHighlighted(null), HIGHLIGHT_MS);
    return () => window.clearTimeout(t);
  }, [highlighted]);

  React.useEffect(() => {
    if (!focusedGroup) return;
    const t = window.setTimeout(() => setFocusedGroup(null), HIGHLIGHT_MS);
    return () => window.clearTimeout(t);
  }, [focusedGroup]);

  const focusCitation = React.useCallback(
    (citation: string) => {
      pendingScroll.current = citationDomId(citation);
      if (!isDesktop) setTab("retained");
      setHighlighted(citation);
      requestScroll();
    },
    [isDesktop],
  );

  const focusGroup = React.useCallback(
    (code: string) => {
      pendingScroll.current = exclusionGroupDomId(code);
      if (!isDesktop) setTab("excluded");
      setFocusedGroup(code);
      requestScroll();
    },
    [isDesktop],
  );

  const retained = (
    <div className="grid gap-2.5">
      {pkg.items.length === 0 ? (
        <EmptyState
          size="sm"
          variant="plain"
          icon={<Inbox />}
          title="Aucun élément retenu"
          description="Aucun candidat n'a franchi la gouvernance et le seuil de pertinence. Consultez la colonne « Exclus »."
        />
      ) : (
        pkg.items.map((item) => (
          <ContextItemCard
            key={item.citation}
            item={item}
            slug={slug}
            bm25Max={bm25Max}
            threshold={minRelevance}
            highlighted={highlighted === item.citation}
            onCitationClick={focusCitation}
          />
        ))
      )}
    </div>
  );

  const excluded = (
    <ExcludedList groups={groups} citationTitles={titles} onRelatedCitation={focusCitation} focusedGroup={focusedGroup} />
  );

  const context = (
    <AssembledContext
      markdown={pkg.context}
      tokensUsed={pkg.tokens_used}
      filename={filename}
      citationTitles={titles}
      activeCitation={highlighted}
      onCitationClick={focusCitation}
    />
  );

  return (
    <div className="grid gap-4">
      <ResultSummary pkg={pkg} slug={slug} actor={actor} onReuse={onReuse} />

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Timer className="size-4 text-primary" aria-hidden />
              Cascade des étapes
            </CardTitle>
            <CardDescription>
              Temps de chaque étape de l&apos;assemblage, proportionnels au total ({formatMs(pkg.timings.total)}).
            </CardDescription>
          </CardHeader>
          <CardContent>
            <StageWaterfall timings={pkg.timings} />
          </CardContent>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Ban className="size-4 text-primary" aria-hidden />
              Exclusions par motif
            </CardTitle>
            <CardDescription>Chaque exclusion est justifiée ; cliquez un motif pour voir les éléments.</CardDescription>
          </CardHeader>
          <CardContent>
            <ExclusionSummary entries={summaryEntries} includedCount={pkg.items.length} onSelect={focusGroup} />
          </CardContent>
        </Card>
      </div>

      {isDesktop ? (
        <div className="grid grid-cols-3 items-start gap-4">
          <Card className="overflow-hidden">
            <ColumnHeader
              icon={<CheckCircle2 className="text-primary" aria-hidden />}
              title="Retenus"
              count={pkg.items.length}
              description="Servis à l'agent, dans l'ordre de présentation."
            />
            <div className="max-h-[56rem] overflow-y-auto p-3">{retained}</div>
          </Card>
          <Card className="overflow-hidden">
            <ColumnHeader
              icon={<Ban className="text-muted-foreground" aria-hidden />}
              title="Exclus"
              count={excludedTotal}
              description="Groupés par motif ; les éléments non autorisés sont caviardés."
            />
            <div className="max-h-[56rem] overflow-y-auto p-3">{excluded}</div>
          </Card>
          <Card className="overflow-hidden">
            <ColumnHeader
              icon={<FileText className="text-primary" aria-hidden />}
              title="Contexte assemblé"
              description="Markdown servi à l'agent, avec ses citations."
            />
            <div className="max-h-[56rem] overflow-y-auto p-3">{context}</div>
          </Card>
        </div>
      ) : (
        <Tabs value={tab} onValueChange={(v) => setTab(v as ColumnKey)}>
          <TabsList variant="pills" className="w-full [&>button]:flex-1">
            <TabsTrigger value="retained" count={pkg.items.length}>
              Retenus
            </TabsTrigger>
            <TabsTrigger value="excluded" count={excludedTotal}>
              Exclus
            </TabsTrigger>
            <TabsTrigger value="context">Contexte</TabsTrigger>
          </TabsList>
          <TabsContent value="retained">{retained}</TabsContent>
          <TabsContent value="excluded">{excluded}</TabsContent>
          <TabsContent value="context">{context}</TabsContent>
        </Tabs>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MessageSquareHeart className="size-4 text-primary" aria-hidden />
            Évaluer ce contexte
          </CardTitle>
          <CardDescription>
            Votre note et vos signalements alimentent l&apos;évaluation (FORGE) ; « Obsolète » propose l&apos;obsolescence de
            l&apos;élément mémoire concerné.
          </CardDescription>
        </CardHeader>
        <CardContent className={cn("max-w-3xl")}>
          <FeedbackWidget slug={slug} requestId={pkg.request_id} items={pkg.items} existing={feedback} />
        </CardContent>
      </Card>
    </div>
  );
}
