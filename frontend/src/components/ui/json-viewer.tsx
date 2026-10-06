"use client";

import * as React from "react";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { CopyButton } from "./code-block";

export interface JsonViewerProps {
  data: unknown;
  /** Depth up to which nodes start expanded (default 1 = only the root). */
  defaultExpandDepth?: number;
  /** Label for the root node. */
  rootLabel?: string;
  /** Tailwind max-height class. */
  maxHeightClassName?: string;
  className?: string;
  hideCopy?: boolean;
}

type JsonValue = unknown;

function isContainer(v: JsonValue): v is Record<string, unknown> | unknown[] {
  return typeof v === "object" && v !== null;
}

function Primitive({ value }: { value: JsonValue }) {
  if (value === null) return <span className="text-subtle-foreground">null</span>;
  if (value === undefined) return <span className="text-subtle-foreground">undefined</span>;
  switch (typeof value) {
    case "string":
      return <span className="break-all text-success">&quot;{value}&quot;</span>;
    case "number":
    case "bigint":
      return <span className="text-blue-700 dark:text-blue-300">{String(value)}</span>;
    case "boolean":
      return <span className="text-violet-700 dark:text-violet-300">{String(value)}</span>;
    default:
      return <span className="text-muted-foreground">{String(value)}</span>;
  }
}

function Node({
  name,
  value,
  depth,
  defaultExpandDepth,
  isLast,
}: {
  name?: string | number;
  value: JsonValue;
  depth: number;
  defaultExpandDepth: number;
  isLast: boolean;
}) {
  const [open, setOpen] = React.useState(depth < defaultExpandDepth);
  const label =
    name === undefined ? null : typeof name === "number" ? (
      <span className="text-subtle-foreground">{name}: </span>
    ) : (
      <span className="text-foreground">&quot;{name}&quot;: </span>
    );

  if (!isContainer(value)) {
    return (
      <div className="pl-5">
        {label}
        <Primitive value={value} />
        {!isLast ? <span className="text-subtle-foreground">,</span> : null}
      </div>
    );
  }

  const isArray = Array.isArray(value);
  const entries: Array<[string | number, unknown]> = isArray
    ? (value as unknown[]).map((v, i) => [i, v])
    : Object.entries(value as Record<string, unknown>);
  const [openCh, closeCh] = isArray ? ["[", "]"] : ["{", "}"];

  if (entries.length === 0) {
    return (
      <div className="pl-5">
        {label}
        <span className="text-subtle-foreground">
          {openCh}
          {closeCh}
        </span>
        {!isLast ? <span className="text-subtle-foreground">,</span> : null}
      </div>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="group/json flex w-full items-center gap-1 rounded text-left hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronRight
          className={cn("size-4 shrink-0 text-subtle-foreground transition-transform", open && "rotate-90")}
          aria-hidden
        />
        <span>
          {label}
          <span className="text-subtle-foreground">{openCh}</span>
          {!open ? (
            <span className="text-subtle-foreground">
              {" "}
              {isArray ? `${entries.length} élément${entries.length > 1 ? "s" : ""}` : `${entries.length} clé${entries.length > 1 ? "s" : ""}`}{" "}
              {closeCh}
              {!isLast ? "," : ""}
            </span>
          ) : null}
        </span>
      </button>
      {open ? (
        <>
          <div className="ml-2 border-l border-border pl-2">
            {entries.map(([k, v], i) => (
              <Node
                key={String(k)}
                name={k}
                value={v}
                depth={depth + 1}
                defaultExpandDepth={defaultExpandDepth}
                isLast={i === entries.length - 1}
              />
            ))}
          </div>
          <div className="pl-5 text-subtle-foreground">
            {closeCh}
            {!isLast ? "," : ""}
          </div>
        </>
      ) : null}
    </div>
  );
}

/** Collapsible JSON tree (keyboard accessible), with a copy button. */
export function JsonViewer({
  data,
  defaultExpandDepth = 1,
  rootLabel,
  maxHeightClassName = "max-h-[28rem]",
  className,
  hideCopy = false,
}: JsonViewerProps) {
  const text = React.useMemo(() => {
    try {
      return JSON.stringify(data, null, 2) ?? "";
    } catch {
      return String(data);
    }
  }, [data]);

  return (
    <div className={cn("group relative rounded-lg border border-border bg-muted/40", className)}>
      {!hideCopy ? (
        <div className="absolute right-1.5 top-1.5 z-10 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          <CopyButton value={text} label="Copier le JSON" className="bg-background/80 backdrop-blur" />
        </div>
      ) : null}
      <div className={cn("overflow-auto p-3 font-mono text-[12.5px] leading-relaxed", maxHeightClassName)}>
        <Node name={rootLabel} value={data} depth={0} defaultExpandDepth={defaultExpandDepth} isLast />
      </div>
    </div>
  );
}
