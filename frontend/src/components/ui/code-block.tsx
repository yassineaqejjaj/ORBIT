"use client";

import * as React from "react";
import { Check, Copy } from "lucide-react";

import { cn, copyToClipboard } from "@/lib/utils";
import { SimpleTooltip } from "./tooltip";

export interface CodeBlockProps {
  code: string;
  /** Shown in the header (e.g. "bash", "json", "markdown"). */
  language?: string;
  /** Header title (e.g. file name). */
  title?: React.ReactNode;
  /** Wrap long lines instead of horizontal scroll. */
  wrap?: boolean;
  showLineNumbers?: boolean;
  /** Tailwind max-height class for the scroll area, e.g. "max-h-96". */
  maxHeightClassName?: string;
  /** Hide the copy button. */
  hideCopy?: boolean;
  className?: string;
}

export function CopyButton({ value, label = "Copier", className }: { value: string; label?: string; className?: string }) {
  const [copied, setCopied] = React.useState(false);
  React.useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(t);
  }, [copied]);
  return (
    <SimpleTooltip content={copied ? "Copié !" : label}>
      <button
        type="button"
        onClick={async () => setCopied(await copyToClipboard(value))}
        className={cn(
          "inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          className,
        )}
        aria-label={copied ? "Copié" : label}
      >
        {copied ? <Check className="size-3.5 text-emerald-600 dark:text-emerald-400" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
      </button>
    </SimpleTooltip>
  );
}

export function CodeBlock({
  code,
  language,
  title,
  wrap = false,
  showLineNumbers = false,
  maxHeightClassName = "max-h-[28rem]",
  hideCopy = false,
  className,
}: CodeBlockProps) {
  const lines = React.useMemo(() => code.replace(/\n$/, "").split("\n"), [code]);
  const hasHeader = Boolean(title || language);
  return (
    <div className={cn("group relative overflow-hidden rounded-lg border border-border bg-muted/40", className)}>
      {hasHeader ? (
        <div className="flex h-9 items-center justify-between gap-2 border-b border-border bg-muted/60 pl-3 pr-1">
          <div className="flex min-w-0 items-center gap-2 text-xs">
            {title ? <span className="truncate font-medium text-foreground">{title}</span> : null}
            {language ? <span className="font-mono text-[11px] uppercase text-subtle-foreground">{language}</span> : null}
          </div>
          {!hideCopy ? <CopyButton value={code} /> : null}
        </div>
      ) : !hideCopy ? (
        <div className="absolute right-1.5 top-1.5 z-10 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          <CopyButton value={code} className="bg-background/80 backdrop-blur" />
        </div>
      ) : null}
      <pre
        className={cn(
          "overflow-auto p-3 font-mono text-[12.5px] leading-relaxed text-foreground",
          wrap ? "whitespace-pre-wrap break-words" : "whitespace-pre",
          maxHeightClassName,
        )}
        tabIndex={0}
      >
        <code>
          {showLineNumbers
            ? lines.map((line, i) => (
                <span key={i} className="table-row">
                  <span className="table-cell select-none pr-4 text-right text-subtle-foreground/70 tabular-nums">{i + 1}</span>
                  <span className="table-cell">{line || " "}</span>
                </span>
              ))
            : code}
        </code>
      </pre>
    </div>
  );
}
