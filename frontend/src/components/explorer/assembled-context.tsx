"use client";

import * as React from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Code2, Download, FileText } from "lucide-react";

import { Button } from "@/components/ui/button";
import { CodeBlock, CopyButton } from "@/components/ui/code-block";
import { EmptyState } from "@/components/ui/empty-state";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { saveBlob } from "@/lib/api/client";
import { citationFromHref, linkifyCitations } from "@/lib/explorer-utils";
import { formatTokens } from "@/lib/format";
import { cn } from "@/lib/utils";
import { CitationBadge } from "./citation-badge";

type ViewMode = "rendered" | "raw";

export interface AssembledContextProps {
  markdown: string;
  tokensUsed: number;
  filename: string;
  citationTitles: Record<string, string>;
  activeCitation?: string | null;
  onCitationClick: (citation: string) => void;
}

function buildComponents(
  citationTitles: Record<string, string>,
  activeCitation: string | null | undefined,
  onCitationClick: (citation: string) => void,
): Components {
  return {
    h1: ({ node: _node, ...props }) => <h1 className="mb-2 mt-5 text-base font-semibold tracking-tight first:mt-0" {...props} />,
    h2: ({ node: _node, ...props }) => (
      <h2
        className="mb-2 mt-5 border-b border-border pb-1.5 text-[13px] font-semibold uppercase tracking-[0.06em] text-foreground first:mt-0"
        {...props}
      />
    ),
    h3: ({ node: _node, ...props }) => <h3 className="mb-1.5 mt-3 text-[13px] font-semibold first:mt-0" {...props} />,
    h4: ({ node: _node, ...props }) => <h4 className="mb-1 mt-3 text-[13px] font-medium first:mt-0" {...props} />,
    p: ({ node: _node, ...props }) => <p className="my-2 leading-relaxed first:mt-0 last:mb-0" {...props} />,
    ul: ({ node: _node, ...props }) => <ul className="my-2 list-disc space-y-1.5 pl-5 marker:text-subtle-foreground" {...props} />,
    ol: ({ node: _node, ...props }) => <ol className="my-2 list-decimal space-y-1.5 pl-5 marker:text-subtle-foreground" {...props} />,
    li: ({ node: _node, ...props }) => <li className="leading-relaxed" {...props} />,
    strong: ({ node: _node, ...props }) => <strong className="font-semibold text-foreground" {...props} />,
    a: ({ node: _node, href, children, ...props }) => {
      const citation = citationFromHref(href);
      if (citation) {
        return (
          <CitationBadge
            citation={citation}
            title={citationTitles[citation]}
            active={activeCitation === citation}
            onClick={onCitationClick}
            className="mx-0.5"
          />
        );
      }
      const external = typeof href === "string" && /^https?:\/\//i.test(href);
      return (
        <a
          href={href}
          className="font-medium text-primary underline underline-offset-2"
          {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
          {...props}
        >
          {children}
        </a>
      );
    },
    blockquote: ({ node: _node, ...props }) => (
      <blockquote className="my-2 border-l-2 border-border-strong pl-3 text-muted-foreground" {...props} />
    ),
    code: ({ node: _node, className, ...props }) => (
      <code className={cn("rounded bg-muted px-1 py-0.5 font-mono text-[12px]", className)} {...props} />
    ),
    pre: ({ node: _node, ...props }) => (
      <pre
        className="my-2 overflow-x-auto rounded-md border border-border bg-muted/50 p-3 font-mono text-[12px] [&_code]:bg-transparent [&_code]:p-0"
        {...props}
      />
    ),
    table: ({ node: _node, ...props }) => (
      <div className="my-2 overflow-x-auto">
        <table className="w-full border-collapse text-[12.5px]" {...props} />
      </div>
    ),
    th: ({ node: _node, ...props }) => <th className="border border-border bg-muted/60 px-2 py-1 text-left font-medium" {...props} />,
    td: ({ node: _node, ...props }) => <td className="border border-border px-2 py-1 align-top" {...props} />,
    hr: ({ node: _node, ...props }) => <hr className="my-4 border-border" {...props} />,
  };
}

/** The Markdown actually served to the agent: rendered with interactive citations, or raw (copy / download). */
export function AssembledContext({
  markdown,
  tokensUsed,
  filename,
  citationTitles,
  activeCitation,
  onCitationClick,
}: AssembledContextProps) {
  const [mode, setMode] = React.useState<ViewMode>("rendered");
  const linked = React.useMemo(() => linkifyCitations(markdown), [markdown]);
  const components = React.useMemo(
    () => buildComponents(citationTitles, activeCitation, onCitationClick),
    [citationTitles, activeCitation, onCitationClick],
  );

  if (!markdown.trim()) {
    return (
      <EmptyState
        size="sm"
        variant="plain"
        icon={<FileText />}
        title="Contexte vide"
        description="Aucun élément n'a été retenu : le contexte servi ne contient que l'en-tête."
      />
    );
  }

  const download = () => saveBlob(new Blob([markdown], { type: "text/markdown;charset=utf-8" }), filename);

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SegmentedControl<ViewMode>
          size="sm"
          value={mode}
          onValueChange={setMode}
          aria-label="Affichage du contexte"
          options={[
            { value: "rendered", label: "Rendu", icon: <FileText aria-hidden /> },
            { value: "raw", label: "Markdown brut", icon: <Code2 aria-hidden /> },
          ]}
        />
        <div className="flex items-center gap-1">
          <span className="mr-1 text-[11.5px] tabular-nums text-subtle-foreground">{formatTokens(tokensUsed)}</span>
          <CopyButton value={markdown} label="Copier le Markdown" />
          <Button variant="ghost" size="icon-xs" onClick={download} aria-label="Télécharger le contexte (.md)" title="Télécharger (.md)">
            <Download aria-hidden />
          </Button>
        </div>
      </div>
      {mode === "rendered" ? (
        <div className="rounded-lg border border-border bg-background px-4 py-3 text-[13px] text-foreground">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
            {linked}
          </ReactMarkdown>
        </div>
      ) : (
        <CodeBlock code={markdown} language="markdown" title={filename} wrap maxHeightClassName="max-h-[40rem]" />
      )}
    </div>
  );
}
