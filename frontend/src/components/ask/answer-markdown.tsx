"use client";

import * as React from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { CitationBadge } from "@/components/explorer/citation-badge";
import { citationFromHref, linkifyCitations } from "@/lib/explorer-utils";

export interface AnswerMarkdownProps {
  markdown: string;
  citationTitles: Record<string, string>;
  onCitationClick: (citation: string) => void;
}

/** Answer of « Demander à ORBIT »: Markdown with clickable [S1] citation badges. */
export function AnswerMarkdown({ markdown, citationTitles, onCitationClick }: AnswerMarkdownProps) {
  const components = React.useMemo<Components>(
    () => ({
      p: ({ node: _node, ...props }) => <p className="my-2 leading-relaxed first:mt-0 last:mb-0" {...props} />,
      ul: ({ node: _node, ...props }) => (
        <ul className="my-2 list-disc space-y-1.5 pl-5 marker:text-subtle-foreground" {...props} />
      ),
      ol: ({ node: _node, ...props }) => (
        <ol className="my-2 list-decimal space-y-1.5 pl-5 marker:text-subtle-foreground" {...props} />
      ),
      li: ({ node: _node, ...props }) => <li className="leading-relaxed" {...props} />,
      strong: ({ node: _node, ...props }) => <strong className="font-semibold text-foreground" {...props} />,
      h3: ({ node: _node, ...props }) => <h3 className="mb-1.5 mt-3 text-[13px] font-semibold first:mt-0" {...props} />,
      a: ({ node: _node, href, children, ...props }) => {
        const citation = citationFromHref(href);
        if (citation) {
          return (
            <CitationBadge
              citation={citation}
              title={citationTitles[citation]}
              onClick={onCitationClick}
              className="mx-0.5 align-baseline"
            />
          );
        }
        return (
          <a href={href} target="_blank" rel="noreferrer" className="text-primary underline-offset-4 hover:underline" {...props}>
            {children}
          </a>
        );
      },
    }),
    [citationTitles, onCitationClick],
  );
  return (
    <div className="text-[13.5px] text-foreground">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {linkifyCitations(markdown)}
      </ReactMarkdown>
    </div>
  );
}
