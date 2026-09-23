"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "./button";

export interface PaginationProps {
  /** Current page (1-based). */
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  /** Hide page-number buttons (prev/next only). */
  compact?: boolean;
  className?: string;
  /** Disable controls (e.g. while fetching). */
  disabled?: boolean;
}

function pageWindow(current: number, last: number): Array<number | "…"> {
  if (last <= 7) return Array.from({ length: last }, (_, i) => i + 1);
  const pages: Array<number | "…"> = [1];
  const start = Math.max(2, current - 1);
  const end = Math.min(last - 1, current + 1);
  if (start > 2) pages.push("…");
  for (let p = start; p <= end; p++) pages.push(p);
  if (end < last - 1) pages.push("…");
  pages.push(last);
  return pages;
}

/** "1–25 sur 132" + previous/next + page numbers. Matches API `Page<T>` (1-based). */
export function Pagination({ page, pageSize, total, onPageChange, compact, className, disabled }: PaginationProps) {
  const last = Math.max(1, Math.ceil(total / Math.max(1, pageSize)));
  const current = Math.min(Math.max(1, page), last);
  const from = total === 0 ? 0 : (current - 1) * pageSize + 1;
  const to = Math.min(total, current * pageSize);

  return (
    <nav
      aria-label="Pagination"
      className={cn("flex flex-wrap items-center justify-between gap-3 text-[13px] text-muted-foreground", className)}
    >
      <p className="tabular-nums" aria-live="polite">
        {total === 0 ? (
          "Aucun résultat"
        ) : (
          <>
            <span className="font-medium text-foreground">
              {formatNumber(from, 0)}–{formatNumber(to, 0)}
            </span>{" "}
            sur <span className="font-medium text-foreground">{formatNumber(total, 0)}</span>
          </>
        )}
      </p>
      {last > 1 ? (
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => onPageChange(current - 1)}
            disabled={disabled || current <= 1}
            aria-label="Page précédente"
          >
            <ChevronLeft aria-hidden />
          </Button>
          {!compact ? (
            <div className="hidden items-center gap-1 sm:flex">
              {pageWindow(current, last).map((p, i) =>
                p === "…" ? (
                  <span key={`gap-${i}`} className="px-1 text-subtle-foreground" aria-hidden>
                    …
                  </span>
                ) : (
                  <Button
                    key={p}
                    variant={p === current ? "secondary" : "ghost"}
                    size="icon-sm"
                    className={cn("tabular-nums", p === current && "text-foreground")}
                    onClick={() => onPageChange(p)}
                    disabled={disabled}
                    aria-current={p === current ? "page" : undefined}
                    aria-label={`Page ${p}`}
                  >
                    {p}
                  </Button>
                ),
              )}
            </div>
          ) : (
            <span className="px-2 tabular-nums">
              {current} / {last}
            </span>
          )}
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => onPageChange(current + 1)}
            disabled={disabled || current >= last}
            aria-label="Page suivante"
          >
            <ChevronRight aria-hidden />
          </Button>
        </div>
      ) : null}
    </nav>
  );
}
