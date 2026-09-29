"use client";

import * as React from "react";
import { ArrowUpRight, ChevronDown, Lock, ShieldCheck } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { ReasonCodeBadge } from "@/components/domain/reason-code-badge";
import { EmptyState } from "@/components/ui/empty-state";
import { SimpleTooltip } from "@/components/ui/tooltip";
import type { ExcludedItem } from "@/lib/api/types";
import { REASON_CODE_META, REASON_GROUP_META, type ReasonCode } from "@/lib/enums";
import { exclusionGroupDomId, type ExclusionGroup } from "@/lib/explorer-utils";
import { formatNumber, formatScore, truncate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { CitationBadge } from "./citation-badge";
import { ItemTypeIcon, itemTypeLabel } from "./item-type-icon";

export const REDACTED_PLACEHOLDER = "Élément non autorisé — détails masqués";

const VISIBLE_PER_GROUP = 5;

export interface ExcludedListProps {
  groups: ExclusionGroup[];
  /** Title lookup for related citations. */
  citationTitles: Record<string, string>;
  onRelatedCitation: (citation: string) => void;
  /** Group to emphasize (after a click in the exclusion summary). */
  focusedGroup?: string | null;
}

function ExcludedRow({
  item,
  citationTitles,
  onRelatedCitation,
}: {
  item: ExcludedItem;
  citationTitles: Record<string, string>;
  onRelatedCitation: (citation: string) => void;
}) {
  if (item.redacted) {
    return (
      <li className="flex items-start gap-2.5 rounded-md border border-dashed border-border-strong bg-muted/40 px-3 py-2.5">
        <span
          className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-slate-200/70 text-slate-600 dark:bg-slate-700/60 dark:text-slate-300"
          aria-hidden
        >
          <Lock className="size-3.5" />
        </span>
        <div className="grid min-w-0 gap-0.5">
          <p className="text-[13px] font-medium text-muted-foreground">{REDACTED_PLACEHOLDER}</p>
          <p className="text-[11.5px] leading-snug text-subtle-foreground">
            {item.reason_detail || "Principe de non-fuite : ni titre, ni extrait, ni identifiant ne sont divulgués."}
          </p>
        </div>
      </li>
    );
  }

  const related = item.related_citation;
  return (
    <li className="flex items-start gap-2.5 rounded-md border border-border bg-card px-3 py-2.5">
      <ItemTypeIcon item={item} size="sm" className="mt-0.5" />
      <div className="grid min-w-0 flex-1 gap-1">
        <div className="flex min-w-0 items-start justify-between gap-2">
          <p className="min-w-0 text-[13px] font-medium leading-snug text-foreground">
            {item.title || <span className="text-muted-foreground">Sans titre</span>}
          </p>
          <SimpleTooltip content="Score final du candidat">
            <span className="shrink-0 font-mono text-[11px] tabular-nums text-subtle-foreground">
              {formatScore(item.scores.final)}
            </span>
          </SimpleTooltip>
        </div>
        {item.excerpt ? (
          <p className="text-[12px] leading-relaxed text-muted-foreground">{truncate(item.excerpt, 220)}</p>
        ) : null}
        <div className="flex flex-wrap items-center gap-1.5 text-[11.5px] text-muted-foreground">
          <span className="font-medium text-foreground/80">{itemTypeLabel(item)}</span>
          {typeof item.classification === "number" ? <ClassificationBadge level={item.classification} showLabel={false} /> : null}
        </div>
        {item.reason_detail ? (
          <p className="text-[11.5px] leading-snug text-foreground/80">
            <span className="text-muted-foreground">Motif : </span>
            {item.reason_detail}
          </p>
        ) : null}
        {related ? (
          <button
            type="button"
            onClick={() => onRelatedCitation(related)}
            className="inline-flex w-fit items-center gap-1.5 text-[11.5px] font-medium text-primary hover:underline"
          >
            Voir l&apos;élément retenu
            <CitationBadge citation={related} title={citationTitles[related]} />
            <ArrowUpRight className="size-3" aria-hidden />
          </button>
        ) : null}
      </div>
    </li>
  );
}

function Group({
  group,
  citationTitles,
  onRelatedCitation,
  focused,
}: {
  group: ExclusionGroup;
  citationTitles: Record<string, string>;
  onRelatedCitation: (citation: string) => void;
  focused: boolean;
}) {
  const [open, setOpen] = React.useState(true);
  const [showAll, setShowAll] = React.useState(false);
  const meta = REASON_CODE_META[group.code as ReasonCode];
  const visible = showAll ? group.items : group.items.slice(0, VISIBLE_PER_GROUP);
  const hiddenCount = group.items.length - visible.length;
  const countersOnly = group.count - group.items.length;
  const panelId = `${exclusionGroupDomId(group.code)}-panel`;

  React.useEffect(() => {
    if (focused) setOpen(true);
  }, [focused]);

  return (
    <section
      id={exclusionGroupDomId(group.code)}
      className={cn(
        "scroll-mt-24 rounded-lg transition-[box-shadow,background-color] duration-300",
        focused && "bg-muted/60 ring-2 ring-ring/30",
      )}
      aria-label={meta?.label ?? group.code}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex w-full items-center gap-2 rounded-md px-1 py-1.5 text-left hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronDown
          className={cn("size-4 shrink-0 text-subtle-foreground transition-transform", !open && "-rotate-90")}
          aria-hidden
        />
        <ReasonCodeBadge code={group.code} size="md" />
        <span className="ml-auto flex items-center gap-2">
          {meta ? (
            <span className="hidden text-[11px] text-subtle-foreground sm:inline">{REASON_GROUP_META[meta.group].label}</span>
          ) : null}
          <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs font-semibold tabular-nums text-foreground">
            {formatNumber(group.count, 0)}
          </span>
        </span>
      </button>
      {open ? (
        <div id={panelId} className="grid gap-2 px-1 pb-2 pt-1">
          {visible.length > 0 ? (
            <ul className="grid gap-2">
              {visible.map((item, i) => (
                <ExcludedRow
                  key={item.id ? `${item.id}-${i}` : `${group.code}-${i}`}
                  item={item}
                  citationTitles={citationTitles}
                  onRelatedCitation={onRelatedCitation}
                />
              ))}
            </ul>
          ) : null}
          {hiddenCount > 0 ? (
            <button
              type="button"
              onClick={() => setShowAll(true)}
              className="w-fit px-1 text-xs font-medium text-primary hover:underline"
            >
              Afficher {formatNumber(hiddenCount, 0)} autre{hiddenCount > 1 ? "s" : ""} élément{hiddenCount > 1 ? "s" : ""}
            </button>
          ) : null}
          {countersOnly > 0 ? (
            <p className="px-1 text-[11.5px] text-subtle-foreground">
              {formatNumber(countersOnly, 0)} exclusion{countersOnly > 1 ? "s" : ""} comptabilisée{countersOnly > 1 ? "s" : ""} sans
              détail (compteurs uniquement).
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/** Excluded candidates grouped by reason code, with non-leaking placeholders for redacted items. */
export function ExcludedList({ groups, citationTitles, onRelatedCitation, focusedGroup }: ExcludedListProps) {
  if (groups.length === 0) {
    return (
      <EmptyState
        size="sm"
        variant="plain"
        icon={<ShieldCheck />}
        title="Aucune exclusion"
        description="Tous les candidats pertinents ont été retenus dans le budget."
      />
    );
  }
  return (
    <div className="grid gap-2">
      {groups.map((group) => (
        <Group
          key={group.code}
          group={group}
          citationTitles={citationTitles}
          onRelatedCitation={onRelatedCitation}
          focused={focusedGroup === group.code}
        />
      ))}
    </div>
  );
}
