"use client";

import * as React from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

const components: Components = {
  h1: ({ node: _node, ...props }) => <h1 className="mb-2 mt-4 text-lg font-semibold tracking-tight first:mt-0" {...props} />,
  h2: ({ node: _node, ...props }) => <h2 className="mb-2 mt-4 text-base font-semibold tracking-tight first:mt-0" {...props} />,
  h3: ({ node: _node, ...props }) => <h3 className="mb-1.5 mt-3 text-sm font-semibold first:mt-0" {...props} />,
  h4: ({ node: _node, ...props }) => <h4 className="mb-1 mt-3 text-sm font-medium first:mt-0" {...props} />,
  p: ({ node: _node, ...props }) => <p className="my-2 leading-relaxed first:mt-0 last:mb-0" {...props} />,
  ul: ({ node: _node, ...props }) => <ul className="my-2 list-disc space-y-1 pl-5" {...props} />,
  ol: ({ node: _node, ...props }) => <ol className="my-2 list-decimal space-y-1 pl-5" {...props} />,
  li: ({ node: _node, ...props }) => <li className="leading-relaxed" {...props} />,
  a: ({ node: _node, ...props }) => (
    <a className="font-medium text-primary underline underline-offset-2" target="_blank" rel="noopener noreferrer" {...props} />
  ),
  blockquote: ({ node: _node, ...props }) => (
    <blockquote className="my-2 border-l-2 border-border-strong pl-3 text-muted-foreground" {...props} />
  ),
  code: ({ node: _node, className, ...props }) => (
    <code className={cn("rounded bg-muted px-1 py-0.5 font-mono text-[12px]", className)} {...props} />
  ),
  pre: ({ node: _node, ...props }) => (
    <pre className="my-2 overflow-x-auto rounded-md border border-border bg-muted/50 p-3 font-mono text-[12px] [&_code]:bg-transparent [&_code]:p-0" {...props} />
  ),
  table: ({ node: _node, ...props }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-[13px]" {...props} />
    </div>
  ),
  th: ({ node: _node, ...props }) => <th className="border border-border bg-muted/60 px-2 py-1 text-left font-medium" {...props} />,
  td: ({ node: _node, ...props }) => <td className="border border-border px-2 py-1 align-top" {...props} />,
  hr: ({ node: _node, ...props }) => <hr className="my-4 border-border" {...props} />,
};

/** Markdown (GFM) rendered with ORBIT typography — raw HTML is never rendered. */
export function MarkdownPreview({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn("text-[13.5px] text-foreground", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
