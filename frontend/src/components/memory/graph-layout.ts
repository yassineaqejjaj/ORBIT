/**
 * Deterministic layered layout for the memory graph (no external dependency).
 *
 * 1. Layers: sources (documents / chunks) on the left (layer 0), memory items in layer 1; items
 *    superseded by another item are pushed one layer to the right of it (chains are followed).
 * 2. Ordering: barycenter sweeps (Sugiyama heuristic) to reduce edge crossings; isolated nodes
 *    are sorted last, by group/label.
 * 3. Tall layers wrap into several sub-columns; columns are vertically centred.
 */
import type { RelationType } from "@/lib/enums";

export type LayoutGroup = "document" | "chunk" | "memory";

export interface LayoutNode {
  id: string;
  group: LayoutGroup;
  /** Secondary ordering key (e.g. kind + label). */
  sortKey: string;
  height: number;
}

export interface LayoutEdge {
  source: string;
  target: string;
  rel_type: RelationType;
}

export interface LayoutOptions {
  nodeWidth: number;
  rowGap: number;
  /** Horizontal gap between two layers. */
  layerGap: number;
  /** Horizontal gap between sub-columns of the same layer. */
  columnGap: number;
  /** Maximum rows per sub-column (default: adaptive). */
  maxRows?: number;
  /** Max number of layers created by supersession chains. */
  maxLayers?: number;
  sweeps?: number;
}

export interface LayoutResult {
  positions: Map<string, { x: number; y: number }>;
  /** Column index of each node (same column ⇒ edge loops on the right side). */
  columns: Map<string, number>;
  width: number;
  height: number;
}

const DEFAULTS = { maxLayers: 6, sweeps: 6 } as const;

export function layoutGraph(nodes: readonly LayoutNode[], edges: readonly LayoutEdge[], options: LayoutOptions): LayoutResult {
  const { nodeWidth, rowGap, layerGap, columnGap } = options;
  const maxLayers = options.maxLayers ?? DEFAULTS.maxLayers;
  const sweeps = options.sweeps ?? DEFAULTS.sweeps;
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const validEdges = edges.filter((e) => e.source !== e.target && byId.has(e.source) && byId.has(e.target));

  // 1. Layer assignment.
  const layer = new Map<string, number>();
  for (const n of nodes) layer.set(n.id, n.group === "memory" ? 1 : 0);
  const supersedes = validEdges.filter(
    (e) => e.rel_type === "supersedes" && byId.get(e.source)?.group === "memory" && byId.get(e.target)?.group === "memory",
  );
  for (let pass = 0; pass < nodes.length && pass < 50; pass++) {
    let changed = false;
    for (const e of supersedes) {
      const wanted = Math.min(maxLayers, (layer.get(e.source) ?? 1) + 1);
      if ((layer.get(e.target) ?? 1) < wanted) {
        layer.set(e.target, wanted);
        changed = true;
      }
    }
    if (!changed) break;
  }

  // Compact layer indices (no empty layers).
  const used = Array.from(new Set(layer.values())).sort((a, b) => a - b);
  const remap = new Map(used.map((value, index) => [value, index]));
  const layers: string[][] = used.map(() => []);
  for (const n of nodes) layers[remap.get(layer.get(n.id) ?? 0) ?? 0]?.push(n.id);

  // Neighbours (undirected) for barycenters.
  const neighbours = new Map<string, string[]>();
  for (const n of nodes) neighbours.set(n.id, []);
  for (const e of validEdges) {
    neighbours.get(e.source)?.push(e.target);
    neighbours.get(e.target)?.push(e.source);
  }

  // 2. Initial order: connected first, then group + sort key.
  const compareStatic = (a: string, b: string) => {
    const na = byId.get(a);
    const nb = byId.get(b);
    const ca = (neighbours.get(a)?.length ?? 0) > 0 ? 0 : 1;
    const cb = (neighbours.get(b)?.length ?? 0) > 0 ? 0 : 1;
    if (ca !== cb) return ca - cb;
    return (na?.sortKey ?? "").localeCompare(nb?.sortKey ?? "", "fr");
  };
  for (const ids of layers) ids.sort(compareStatic);

  const position = new Map<string, number>();
  const refreshPositions = () => {
    for (const ids of layers) ids.forEach((id, index) => position.set(id, ids.length > 1 ? index / (ids.length - 1) : 0.5));
  };
  refreshPositions();

  const reorder = (ids: string[], fixed: ReadonlySet<string>) => {
    const scores = new Map<string, number>();
    for (const id of ids) {
      const ns = (neighbours.get(id) ?? []).filter((n) => fixed.has(n));
      if (ns.length === 0) continue;
      scores.set(id, ns.reduce((sum, n) => sum + (position.get(n) ?? 0.5), 0) / ns.length);
    }
    ids.sort((a, b) => {
      const sa = scores.get(a);
      const sb = scores.get(b);
      if (sa !== undefined && sb !== undefined && sa !== sb) return sa - sb;
      if (sa !== undefined && sb === undefined) return -1;
      if (sa === undefined && sb !== undefined) return 1;
      return compareStatic(a, b);
    });
  };

  for (let s = 0; s < sweeps; s++) {
    const forward = s % 2 === 0;
    const order = forward ? layers.map((_, i) => i) : layers.map((_, i) => layers.length - 1 - i);
    for (const li of order) {
      const ids = layers[li];
      if (!ids || ids.length < 2) continue;
      const fixed = new Set<string>();
      layers.forEach((other, oi) => {
        if (oi !== li) other.forEach((id) => fixed.add(id));
      });
      // Same-layer relations (contradicts) also pull nodes together.
      ids.forEach((id) => fixed.add(id));
      reorder(ids, fixed);
      refreshPositions();
    }
  }

  // 3. Coordinates with column wrapping.
  const total = nodes.length;
  const maxRows = options.maxRows ?? Math.max(8, Math.ceil(Math.sqrt(Math.max(total, 1)) * 1.6));
  const columns: string[][] = [];
  const layerOfColumn: number[] = [];
  layers.forEach((ids, li) => {
    if (ids.length === 0) return;
    const cols = Math.ceil(ids.length / maxRows);
    const rows = Math.ceil(ids.length / cols);
    for (let c = 0; c < cols; c++) {
      columns.push(ids.slice(c * rows, (c + 1) * rows));
      layerOfColumn.push(li);
    }
  });

  const columnHeight = (ids: readonly string[]) =>
    ids.reduce((sum, id) => sum + (byId.get(id)?.height ?? 40), 0) + Math.max(0, ids.length - 1) * rowGap;
  const tallest = Math.max(0, ...columns.map(columnHeight));

  const positions = new Map<string, { x: number; y: number }>();
  const columnIndex = new Map<string, number>();
  let x = 0;
  columns.forEach((ids, ci) => {
    if (ci > 0) x += nodeWidth + (layerOfColumn[ci] !== layerOfColumn[ci - 1] ? layerGap : columnGap);
    let y = (tallest - columnHeight(ids)) / 2;
    for (const id of ids) {
      positions.set(id, { x, y });
      columnIndex.set(id, ci);
      y += (byId.get(id)?.height ?? 40) + rowGap;
    }
  });

  return { positions, columns: columnIndex, width: x + nodeWidth, height: tallest };
}
