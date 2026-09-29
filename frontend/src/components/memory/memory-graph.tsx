"use client";

import "@xyflow/react/dist/style.css";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  useNodesState,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import { ChevronDown, ChevronUp, Network } from "lucide-react";

import { EnumIcon } from "@/components/domain/enum-icon";
import { SourceKindIcon } from "@/components/domain/source-kind-icon";
import { useTheme } from "@/components/providers/theme-provider";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useMemoryGraph } from "@/lib/api/hooks";
import type { MemoryGraph, MemoryGraphEdge, MemoryGraphNode } from "@/lib/api/types";
import {
  getMeta,
  isEnumValue,
  MEMORY_KIND_META,
  MEMORY_KINDS,
  MEMORY_STATUS_META,
  RELATION_TYPE_META,
  SOURCE_KIND_META,
  type MemoryKind,
  type RelationType,
  type Tone,
} from "@/lib/enums";
import { formatNumber, plural } from "@/lib/format";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

import { layoutGraph, type LayoutGroup } from "./graph-layout";

/* -------------------------------------------------------------------------- */
/* Constants                                                                  */
/* -------------------------------------------------------------------------- */

const NODE_WIDTH = 224;
const MEMORY_HEIGHT = 36;
const SOURCE_HEIGHT = 50;
const DIMMED_STATUSES = new Set(["superseded", "obsolete", "forgotten"]);
/** Up to this many edges, every edge shows its relation label. */
const FULL_LABEL_MAX_EDGES = 40;

/** Hex colors (SVG attributes cannot always resolve CSS variables, e.g. markers, minimap). */
const TONE_HEX: Record<Tone, string> = {
  neutral: "#94a3b8",
  teal: "#14b8a6",
  green: "#10b981",
  amber: "#f59e0b",
  red: "#ef4444",
  blue: "#3b82f6",
  sky: "#0ea5e9",
  violet: "#8b5cf6",
  orange: "#f97316",
  pink: "#ec4899",
};

interface EdgeStyleSpec {
  light: string;
  dark: string;
  dash?: string;
  width: number;
  /** Label always visible (otherwise only when the edge is focused). */
  alwaysLabel: boolean;
}

const EDGE_STYLES: Record<RelationType, EdgeStyleSpec> = {
  supersedes: { light: "#dc2626", dark: "#f87171", dash: "6 4", width: 1.75, alwaysLabel: true },
  contradicts: { light: "#d97706", dark: "#fbbf24", width: 2, alwaysLabel: true },
  derived_from: { light: "#94a3b8", dark: "#64748b", width: 1.25, alwaysLabel: false },
  mentions: { light: "#cbd5e1", dark: "#475569", dash: "2 3", width: 1, alwaysLabel: false },
  constrains: { light: "#ea580c", dark: "#fb923c", width: 1.25, alwaysLabel: false },
  relates_to: { light: "#0284c7", dark: "#38bdf8", dash: "2 3", width: 1, alwaysLabel: false },
};

function edgeSpec(rel: string): EdgeStyleSpec {
  return isEnumValue(Object.keys(EDGE_STYLES) as RelationType[], rel) ? EDGE_STYLES[rel] : EDGE_STYLES.relates_to;
}

/* -------------------------------------------------------------------------- */
/* Focus context (hover / selection highlighting without re-creating nodes)    */
/* -------------------------------------------------------------------------- */

interface FocusValue {
  focusId: string | null;
  related: ReadonlySet<string>;
  selectedId: string | null;
}

const FocusContext = React.createContext<FocusValue>({ focusId: null, related: new Set(), selectedId: null });

function useNodeFocus(id: string) {
  const { focusId, related, selectedId } = React.useContext(FocusContext);
  const faded = focusId !== null && id !== focusId && !related.has(id);
  return { faded, selected: selectedId === id, focused: focusId === id };
}

/* -------------------------------------------------------------------------- */
/* Custom nodes                                                               */
/* -------------------------------------------------------------------------- */

type MemoryNodeData = { label: string; kind: string | null; status: string | null };
type SourceNodeData = { label: string; kind: string | null; status: string | null; nodeType: "document" | "chunk" };
type MemoryFlowNode = Node<MemoryNodeData, "memory">;
type SourceFlowNode = Node<SourceNodeData, "source">;
type FlowNode = MemoryFlowNode | SourceFlowNode;

const HANDLE_CLASS = "!size-1.5 !min-h-0 !min-w-0 !border-0 !bg-transparent";

function Handles() {
  return (
    <>
      <Handle id="l-t" type="target" position={Position.Left} isConnectable={false} className={HANDLE_CLASS} />
      <Handle id="l-s" type="source" position={Position.Left} isConnectable={false} className={HANDLE_CLASS} />
      <Handle id="r-t" type="target" position={Position.Right} isConnectable={false} className={HANDLE_CLASS} />
      <Handle id="r-s" type="source" position={Position.Right} isConnectable={false} className={HANDLE_CLASS} />
    </>
  );
}

function MemoryNode({ id, data }: NodeProps<MemoryFlowNode>) {
  const { faded, selected, focused } = useNodeFocus(id);
  const meta = getMeta(MEMORY_KIND_META, data.kind);
  const dimmed = DIMMED_STATUSES.has(data.status ?? "");
  const statusMeta = getMeta(MEMORY_STATUS_META, data.status);
  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-full px-3 text-[11.5px] font-medium ring-1 ring-inset shadow-xs transition-[opacity,box-shadow] duration-150",
        toneClasses(meta.tone).soft,
        dimmed && "opacity-45 outline outline-1 outline-dashed outline-slate-400/70",
        data.status === "superseded" && "line-through",
        faded && "opacity-20",
        (selected || focused) && "shadow-md ring-2 ring-ring",
      )}
      style={{ width: NODE_WIDTH, height: MEMORY_HEIGHT }}
      title={`${meta.label} · ${statusMeta.label} — ${data.label}`}
    >
      <Handles />
      {meta.icon ? <EnumIcon name={meta.icon} className="size-3.5 shrink-0" /> : null}
      <span className="min-w-0 flex-1 truncate">{data.label}</span>
      {data.status === "proposed" ? (
        <span className={cn("size-1.5 shrink-0 rounded-full", toneClasses("amber").dot)} aria-label="Proposé" />
      ) : null}
    </div>
  );
}

function SourceNode({ id, data }: NodeProps<SourceFlowNode>) {
  const { faded, selected, focused } = useNodeFocus(id);
  const kindLabel = data.nodeType === "chunk" ? "Extrait de source" : getMeta(SOURCE_KIND_META, data.kind).label;
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-lg border border-border bg-card px-2.5 shadow-xs transition-[opacity,box-shadow] duration-150",
        data.status === "forgotten" && "opacity-45",
        faded && "opacity-20",
        (selected || focused) && "shadow-md ring-2 ring-ring",
      )}
      style={{ width: NODE_WIDTH, height: SOURCE_HEIGHT }}
      title={data.label}
    >
      <Handles />
      <SourceKindIcon kind={data.nodeType === "chunk" ? "document" : data.kind} chip size="sm" />
      <span className="grid min-w-0 leading-tight">
        <span className="truncate text-[12px] font-medium text-foreground">{data.label}</span>
        <span className="truncate text-[10.5px] text-muted-foreground">{kindLabel}</span>
      </span>
    </div>
  );
}

const NODE_TYPES: NodeTypes = { memory: MemoryNode, source: SourceNode };

/* -------------------------------------------------------------------------- */
/* Graph → flow                                                               */
/* -------------------------------------------------------------------------- */

function groupOf(node: MemoryGraphNode): LayoutGroup {
  if (node.type === "memory") return "memory";
  return node.type === "chunk" ? "chunk" : "document";
}

function kindRank(kind: string | null): number {
  const index = MEMORY_KINDS.indexOf((kind ?? "") as MemoryKind);
  return index === -1 ? 99 : index;
}

interface Built {
  nodes: FlowNode[];
  edges: MemoryGraphEdge[];
  columns: Map<string, number>;
}

function buildNodes(graph: MemoryGraph): Built {
  const ids = new Set(graph.nodes.map((n) => n.id));
  const edges = graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
  const layout = layoutGraph(
    graph.nodes.map((n) => ({
      id: n.id,
      group: groupOf(n),
      sortKey: `${String(kindRank(n.kind)).padStart(2, "0")}-${DIMMED_STATUSES.has(n.status ?? "") ? 1 : 0}-${n.label}`,
      height: n.type === "memory" ? MEMORY_HEIGHT : SOURCE_HEIGHT,
    })),
    edges,
    { nodeWidth: NODE_WIDTH, rowGap: 14, layerGap: 150, columnGap: 36 },
  );
  const nodes: FlowNode[] = graph.nodes.map((n) => {
    const position = layout.positions.get(n.id) ?? { x: 0, y: 0 };
    if (n.type === "memory") {
      return { id: n.id, type: "memory", position, data: { label: n.label, kind: n.kind, status: n.status } };
    }
    return {
      id: n.id,
      type: "source",
      position,
      data: { label: n.label, kind: n.kind, status: n.status, nodeType: n.type === "chunk" ? "chunk" : "document" },
    };
  });
  return { nodes, edges, columns: layout.columns };
}

/* -------------------------------------------------------------------------- */
/* Legend                                                                     */
/* -------------------------------------------------------------------------- */

function LegendLine({ rel, dark }: { rel: RelationType; dark: boolean }) {
  const spec = EDGE_STYLES[rel];
  return (
    <span className="flex items-center gap-2">
      <svg width="28" height="8" aria-hidden className="shrink-0">
        <line
          x1="1"
          y1="4"
          x2="27"
          y2="4"
          stroke={dark ? spec.dark : spec.light}
          strokeWidth={spec.width + 0.25}
          strokeDasharray={spec.dash}
        />
      </svg>
      {RELATION_TYPE_META[rel].label}
    </span>
  );
}

function GraphLegend({ dark }: { dark: boolean }) {
  const [open, setOpen] = React.useState(true);
  return (
    <div className="w-56 rounded-lg border border-border bg-popover/95 text-[11.5px] text-foreground shadow-md backdrop-blur">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-xs font-semibold"
      >
        Légende
        {open ? <ChevronUp className="size-3.5" aria-hidden /> : <ChevronDown className="size-3.5" aria-hidden />}
      </button>
      {open ? (
        <div className="grid gap-2.5 border-t border-border px-3 pb-3 pt-2">
          <div className="grid gap-1.5">
            <span className="text-[10.5px] font-semibold uppercase tracking-wide text-subtle-foreground">Nœuds</span>
            <span className="flex items-center gap-2">
              <span className="h-3.5 w-6 shrink-0 rounded-[4px] border border-border-strong bg-card" aria-hidden />
              Document source
            </span>
            <span className="flex flex-wrap items-center gap-1">
              {MEMORY_KINDS.map((kind) => (
                <span
                  key={kind}
                  className={cn("inline-flex h-4 items-center rounded-full px-1.5 text-[10px] ring-1 ring-inset", toneClasses(MEMORY_KIND_META[kind].tone).soft)}
                >
                  {MEMORY_KIND_META[kind].label}
                </span>
              ))}
            </span>
            <span className="flex items-center gap-2 text-muted-foreground">
              <span className="h-3.5 w-6 shrink-0 rounded-full bg-slate-200 opacity-50 outline outline-1 outline-dashed outline-slate-400 dark:bg-slate-700" aria-hidden />
              Remplacé, obsolète ou oublié
            </span>
          </div>
          <div className="grid gap-1.5">
            <span className="text-[10.5px] font-semibold uppercase tracking-wide text-subtle-foreground">Relations</span>
            <LegendLine rel="supersedes" dark={dark} />
            <LegendLine rel="contradicts" dark={dark} />
            <LegendLine rel="derived_from" dark={dark} />
            <LegendLine rel="constrains" dark={dark} />
            <LegendLine rel="relates_to" dark={dark} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Canvas                                                                     */
/* -------------------------------------------------------------------------- */

function GraphCanvas({
  slug,
  graph,
  selectedId,
  onSelect,
}: {
  slug: string;
  graph: MemoryGraph;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const router = useRouter();
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";
  const built = React.useMemo(() => buildNodes(graph), [graph]);
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(built.nodes);
  const [hoverId, setHoverId] = React.useState<string | null>(null);

  React.useEffect(() => {
    setNodes(built.nodes);
  }, [built, setNodes]);

  const adjacency = React.useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const e of built.edges) {
      if (!map.has(e.source)) map.set(e.source, new Set());
      if (!map.has(e.target)) map.set(e.target, new Set());
      map.get(e.source)?.add(e.target);
      map.get(e.target)?.add(e.source);
    }
    return map;
  }, [built.edges]);

  const focusId = hoverId ?? (selectedId && adjacency.has(selectedId) ? selectedId : null);
  const focus = React.useMemo<FocusValue>(
    () => ({ focusId, related: (focusId && adjacency.get(focusId)) || new Set<string>(), selectedId }),
    [focusId, adjacency, selectedId],
  );

  const labelBg = dark ? "#10161d" : "#ffffff";
  const edges = React.useMemo<Edge[]>(
    () =>
      built.edges.map((e, index) => {
        const spec = edgeSpec(e.rel_type);
        const color = dark ? spec.dark : spec.light;
        const connected = focusId !== null && (e.source === focusId || e.target === focusId);
        const faded = focusId !== null && !connected;
        const sc = built.columns.get(e.source) ?? 0;
        const tc = built.columns.get(e.target) ?? 0;
        const [sourceHandle, targetHandle] = sc === tc ? ["r-s", "r-t"] : sc < tc ? ["r-s", "l-t"] : ["l-s", "r-t"];
        // Small graphs label every edge; larger ones keep the key relations labelled (others on focus).
        const showLabel = spec.alwaysLabel || connected || built.edges.length <= FULL_LABEL_MAX_EDGES;
        return {
          id: `${e.source}:${e.rel_type}:${e.target}:${index}`,
          source: e.source,
          target: e.target,
          sourceHandle,
          targetHandle,
          type: "default",
          label: showLabel ? getMeta(RELATION_TYPE_META, e.rel_type).label : undefined,
          labelStyle: { fill: color, fontSize: 10, fontWeight: 600 },
          labelBgStyle: { fill: labelBg, fillOpacity: 0.92 },
          labelBgPadding: [4, 2] as [number, number],
          labelBgBorderRadius: 4,
          style: {
            stroke: color,
            strokeWidth: connected ? spec.width + 0.75 : spec.width,
            strokeDasharray: spec.dash,
            opacity: faded ? 0.12 : 1,
          },
          markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
          zIndex: connected ? 10 : 0,
          focusable: false,
        } satisfies Edge;
      }),
    [built, dark, focusId, labelBg],
  );

  const onNodeClick = React.useCallback<NodeMouseHandler<FlowNode>>(
    (_event, node) => {
      if (node.type === "memory") onSelect(node.id);
      else if (node.type === "source" && node.data.nodeType === "document") {
        router.push(`/projects/${encodeURIComponent(slug)}/sources/${encodeURIComponent(node.id)}`);
      }
    },
    [onSelect, router, slug],
  );

  const memoryCount = graph.nodes.filter((n) => n.type === "memory").length;
  const sourceCount = graph.nodes.length - memoryCount;

  return (
    <FocusContext.Provider value={focus}>
      <ReactFlow<FlowNode, Edge>
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        nodeTypes={NODE_TYPES}
        onNodeClick={onNodeClick}
        onNodeMouseEnter={(_e, node) => setHoverId(node.id)}
        onNodeMouseLeave={() => setHoverId(null)}
        onPaneClick={() => setHoverId(null)}
        colorMode={dark ? "dark" : "light"}
        nodesConnectable={false}
        edgesFocusable={false}
        elementsSelectable={false}
        fitView
        fitViewOptions={{ padding: 0.15, maxZoom: 1.1 }}
        minZoom={0.15}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        className="!bg-transparent"
        aria-label="Graphe des relations mémoire"
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1} color={dark ? "#1e2934" : "#d5dde5"} />
        <Controls showInteractive={false} position="bottom-left" />
        <MiniMap
          pannable
          zoomable
          position="bottom-right"
          className="!hidden !rounded-lg !border !border-border sm:!block"
          maskColor={dark ? "rgba(10,14,19,0.65)" : "rgba(241,244,246,0.65)"}
          nodeColor={(node) => {
            const n = node as FlowNode;
            if (n.type === "source") return dark ? "#334155" : "#cbd5e1";
            return TONE_HEX[getMeta(MEMORY_KIND_META, n.data.kind).tone];
          }}
          nodeBorderRadius={8}
        />
        <Panel position="top-left">
          <GraphLegend dark={dark} />
        </Panel>
        <Panel position="top-right">
          <div className="rounded-lg border border-border bg-popover/95 px-3 py-2 text-[11.5px] text-muted-foreground shadow-sm backdrop-blur">
            <span className="font-semibold tabular-nums text-foreground">{formatNumber(memoryCount, 0)}</span> mémoires ·{" "}
            <span className="font-semibold tabular-nums text-foreground">{formatNumber(sourceCount, 0)}</span> sources ·{" "}
            {plural(built.edges.length, "relation")}
          </div>
        </Panel>
      </ReactFlow>
    </FocusContext.Provider>
  );
}

export interface MemoryGraphViewProps {
  slug: string;
  limit: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
  className?: string;
}

/** "Graphe" view: documents and memory items with their relations (supersedes, contradicts, derived_from…). */
export function MemoryGraphView({ slug, limit, selectedId, onSelect, className }: MemoryGraphViewProps) {
  const query = useMemoryGraph(slug, limit);

  return (
    <div
      className={cn(
        "relative h-[calc(100dvh-15rem)] min-h-[480px] overflow-hidden rounded-xl border border-border bg-surface shadow-xs",
        className,
      )}
    >
      {query.isPending ? (
        <div className="grid h-full grid-cols-3 gap-10 p-10" aria-busy="true" aria-label="Chargement du graphe">
          {Array.from({ length: 3 }, (_, c) => (
            <div key={c} className="grid content-center gap-3">
              {Array.from({ length: 6 - c }, (_, r) => (
                <Skeleton key={r} className={cn("h-9", c === 0 ? "rounded-lg" : "rounded-full")} />
              ))}
            </div>
          ))}
        </div>
      ) : query.isError ? (
        <div className="grid h-full place-items-center p-6">
          <ErrorState error={query.error} onRetry={() => void query.refetch()} variant="plain" />
        </div>
      ) : query.data.nodes.length === 0 ? (
        <div className="grid h-full place-items-center p-6">
          <EmptyState
            variant="plain"
            icon={<Network />}
            title="Aucune relation à afficher"
            description="Le graphe se remplit au fil des ingestions : décisions extraites, remplacements et contradictions détectés."
          />
        </div>
      ) : (
        // Re-mount on limit change so the viewport fits the new graph.
        <GraphCanvas key={limit} slug={slug} graph={query.data} selectedId={selectedId} onSelect={onSelect} />
      )}
    </div>
  );
}
