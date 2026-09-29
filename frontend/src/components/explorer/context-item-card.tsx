"use client";

import * as React from "react";
import Link from "next/link";
import { CalendarDays, ExternalLink, EyeOff, Hash } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { ReasonCodeBadge } from "@/components/domain/reason-code-badge";
import { ScopeBadge } from "@/components/domain/scope-badge";
import { Badge } from "@/components/ui/badge";
import { SimpleTooltip } from "@/components/ui/tooltip";
import type { ContextItem } from "@/lib/api/types";
import { citationDomId } from "@/lib/explorer-utils";
import { formatAgeDays, formatDate, formatTokens } from "@/lib/format";
import { cn } from "@/lib/utils";
import { CitationBadge } from "./citation-badge";
import { ItemTypeIcon, itemTypeLabel } from "./item-type-icon";
import { ScoresPopover } from "./scores-popover";

export interface ContextItemCardProps {
  item: ContextItem;
  slug: string;
  bm25Max: number;
  threshold?: number;
  /** Item currently focused from a citation link. */
  highlighted?: boolean;
  onCitationClick?: (citation: string) => void;
}

/** Link to the page of the underlying object (document page, or the memory screen focused on the item). */
export function itemHref(
  slug: string,
  item: Pick<ContextItem, "candidate_type" | "document_id" | "memory_item_id">,
): string | null {
  const base = `/projects/${encodeURIComponent(slug)}`;
  if (item.document_id) return `${base}/sources/${encodeURIComponent(item.document_id)}`;
  if (item.memory_item_id) return `${base}/memory?item=${encodeURIComponent(item.memory_item_id)}`;
  return null;
}

const EXCERPT_CLAMP = 280;

/** Retained item: citation, type, title, served excerpt, scores, date, classification, PII and reason. */
export function ContextItemCard({ item, slug, bm25Max, threshold, highlighted, onCitationClick }: ContextItemCardProps) {
  const [expanded, setExpanded] = React.useState(false);
  const href = itemHref(slug, item);
  const long = item.excerpt.length > EXCERPT_CLAMP;
  const typeLabel = itemTypeLabel(item);

  return (
    <article
      id={citationDomId(item.citation)}
      tabIndex={-1}
      aria-label={`${item.citation} — ${item.title}`}
      className={cn(
        "scroll-mt-24 rounded-lg border bg-card p-3 transition-[border-color,box-shadow,background-color] duration-300 focus:outline-none",
        highlighted
          ? "border-primary/60 bg-brand-soft/40 shadow-md ring-2 ring-primary/25"
          : "border-border hover:border-border-strong",
      )}
    >
      <header className="flex items-start gap-2.5">
        <ItemTypeIcon item={item} size="sm" className="mt-0.5" />
        <div className="grid min-w-0 flex-1 gap-1">
          <div className="flex min-w-0 items-start gap-1.5">
            <CitationBadge citation={item.citation} onClick={onCitationClick} active={highlighted} className="mt-px" />
            <h4 className="min-w-0 text-[13px] font-semibold leading-snug text-foreground">
              {href ? (
                <Link href={href} className="hover:text-primary hover:underline hover:underline-offset-2">
                  {item.title}
                </Link>
              ) : (
                item.title
              )}
              {item.uri ? (
                <a
                  href={item.uri}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-1 inline-flex align-middle text-subtle-foreground hover:text-foreground"
                  aria-label="Ouvrir la source d'origine"
                >
                  <ExternalLink className="size-3" aria-hidden />
                </a>
              ) : null}
            </h4>
          </div>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-muted-foreground">
            <span className="font-medium text-foreground/80">{typeLabel}</span>
            {item.memory_scope ? <ScopeBadge scope={item.memory_scope} /> : null}
            {typeof item.version === "number" ? (
              <span className="inline-flex items-center gap-0.5">
                <Hash className="size-3" aria-hidden />v{item.version}
              </span>
            ) : null}
            {item.date ? (
              <SimpleTooltip content={formatDate(item.date)}>
                <span className="inline-flex items-center gap-1 tabular-nums">
                  <CalendarDays className="size-3" aria-hidden />
                  {formatAgeDays(item.date)}
                </span>
              </SimpleTooltip>
            ) : null}
            <span className="tabular-nums">{formatTokens(item.tokens)}</span>
          </div>
        </div>
      </header>

      <div className="mt-2.5">
        <p className="whitespace-pre-line text-[13px] leading-relaxed text-foreground/90">
          {long && !expanded ? `${item.excerpt.slice(0, EXCERPT_CLAMP).trimEnd()}…` : item.excerpt}
        </p>
        {long ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mt-1 text-xs font-medium text-primary hover:underline"
            aria-expanded={expanded}
          >
            {expanded ? "Réduire" : "Afficher tout l'extrait"}
          </button>
        ) : null}
      </div>

      <footer className="mt-2.5 grid gap-1.5 border-t border-border pt-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <ReasonCodeBadge code={item.reason_code} detail={item.reason_detail} short />
          <ClassificationBadge level={item.classification} showLabel={false} />
          {item.pii_redacted ? (
            <Badge tone="pink" icon={<EyeOff aria-hidden />} title="Les données personnelles ont été remplacées avant d'être servies">
              Données perso. caviardées
            </Badge>
          ) : null}
          <ScoresPopover scores={item.scores} bm25Max={bm25Max} threshold={threshold} className="ml-auto" />
        </div>
        {item.reason_detail ? <p className="text-[11.5px] leading-snug text-muted-foreground">{item.reason_detail}</p> : null}
      </footer>
    </article>
  );
}
