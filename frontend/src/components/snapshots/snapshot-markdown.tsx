"use client";

import * as React from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { SimpleTooltip } from "@/components/ui/tooltip";
import type { SnapshotItem } from "@/lib/api/types";
import { CANDIDATE_TYPE_META, getMeta, MEMORY_KIND_META, SOURCE_KIND_META } from "@/lib/enums";
import { truncate } from "@/lib/format";
import { cn } from "@/lib/utils";

import { CITATION_HREF_PREFIX, linkCitations } from "./snapshot-utils";

export interface SnapshotMarkdownProps {
  content: string;
  /** Snapshot items, used to describe citations on hover. */
  items?: readonly SnapshotItem[];
  /** Called when a citation badge is clicked. */
  onCitationClick?: (citation: string) => void;
  className?: string;
}

function CitationBadge({
  citation,
  item,
  onClick,
}: {
  citation: string;
  item: SnapshotItem | undefined;
  onClick?: (citation: string) => void;
}) {
  const typeLabel = item
    ? item.memory_kind
      ? getMeta(MEMORY_KIND_META, item.memory_kind).label
      : item.source_kind
        ? getMeta(SOURCE_KIND_META, item.source_kind).label
        : getMeta(CANDIDATE_TYPE_META, item.candidate_type).label
    : null;
  const badge = (
    <button
      type="button"
      onClick={() => onClick?.(citation)}
      className={cn(
        "mx-0.5 inline-flex h-[1.15rem] -translate-y-px items-center rounded px-1 align-middle font-mono text-[10.5px] font-semibold leading-none ring-1 ring-inset transition-colors",
        "bg-teal-50 text-teal-800 ring-teal-600/25 hover:bg-teal-100 dark:bg-teal-400/10 dark:text-teal-300 dark:ring-teal-400/30 dark:hover:bg-teal-400/20",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        item?.forgotten && "bg-red-50 text-red-700 ring-red-600/25 line-through dark:bg-red-400/10 dark:text-red-300",
      )}
      aria-label={item ? `Citation ${citation} : ${item.title}` : `Citation ${citation}`}
    >
      {citation}
    </button>
  );
  if (!item) return badge;
  return (
    <SimpleTooltip
      content={
        <span className="grid max-w-72 gap-0.5">
          <span className="font-medium">{item.forgotten ? "Contenu oublié" : truncate(item.title, 90)}</span>
          <span className="opacity-75">
            {typeLabel}
            {item.version ? ` · v${item.version}` : ""}
          </span>
        </span>
      }
    >
      {badge}
    </SimpleTooltip>
  );
}

/** Markdown (GFM) with ORBIT typography where `[S1]` citations render as interactive badges. */
export function SnapshotMarkdown({ content, items, onCitationClick, className }: SnapshotMarkdownProps) {
  const byCitation = React.useMemo(() => new Map((items ?? []).map((i) => [i.citation, i])), [items]);
  const source = React.useMemo(() => linkCitations(content), [content]);

  const components = React.useMemo<Components>(
    () => ({
      h1: ({ node: _node, ...props }) => <h1 className="mb-3 mt-6 text-lg font-semibold tracking-tight first:mt-0" {...props} />,
      h2: ({ node: _node, ...props }) => (
        <h2 className="mb-2 mt-6 border-b border-border pb-1.5 text-[15px] font-semibold tracking-tight first:mt-0" {...props} />
      ),
      h3: ({ node: _node, ...props }) => <h3 className="mb-1.5 mt-4 text-sm font-semibold first:mt-0" {...props} />,
      h4: ({ node: _node, ...props }) => <h4 className="mb-1 mt-3 text-sm font-medium first:mt-0" {...props} />,
      p: ({ node: _node, ...props }) => <p className="my-2 leading-relaxed first:mt-0 last:mb-0" {...props} />,
      ul: ({ node: _node, ...props }) => <ul className="my-2 list-disc space-y-1 pl-5" {...props} />,
      ol: ({ node: _node, ...props }) => <ol className="my-2 list-decimal space-y-1 pl-5" {...props} />,
      li: ({ node: _node, ...props }) => <li className="leading-relaxed marker:text-subtle-foreground" {...props} />,
      a: ({ node: _node, href, children, ...props }) => {
        if (href?.startsWith(CITATION_HREF_PREFIX)) {
          const citation = href.slice(CITATION_HREF_PREFIX.length);
          return <CitationBadge citation={citation} item={byCitation.get(citation)} onClick={onCitationClick} />;
        }
        return (
          <a
            href={href}
            className="font-medium text-primary underline underline-offset-2"
            target="_blank"
            rel="noopener noreferrer"
            {...props}
          >
            {children}
          </a>
        );
      },
      blockquote: ({ node: _node, ...props }) => (
        <blockquote className="my-2 border-l-2 border-border-strong pl-3 text-muted-foreground" {...props} />
      ),
      code: ({ node: _node, className: codeClass, ...props }) => (
        <code className={cn("rounded bg-muted px-1 py-0.5 font-mono text-[12px]", codeClass)} {...props} />
      ),
      pre: ({ node: _node, ...props }) => (
        <pre
          className="my-2 overflow-x-auto rounded-md border border-border bg-muted/50 p-3 font-mono text-[12px] [&_code]:bg-transparent [&_code]:p-0"
          {...props}
        />
      ),
      table: ({ node: _node, ...props }) => (
        <div className="my-3 overflow-x-auto">
          <table className="w-full border-collapse text-[13px]" {...props} />
        </div>
      ),
      th: ({ node: _node, ...props }) => <th className="border border-border bg-muted/60 px-2 py-1 text-left font-medium" {...props} />,
      td: ({ node: _node, ...props }) => <td className="border border-border px-2 py-1 align-top" {...props} />,
      hr: ({ node: _node, ...props }) => <hr className="my-4 border-border" {...props} />,
    }),
    [byCitation, onCitationClick],
  );

  return (
    <div className={cn("text-[13.5px] text-foreground", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {source}
      </ReactMarkdown>
    </div>
  );
}
