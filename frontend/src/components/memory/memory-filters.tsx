"use client";

import * as React from "react";
import { FilterX, Search, X } from "lucide-react";

import { EnumIcon } from "@/components/domain/enum-icon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SegmentedControl, type SegmentedOption } from "@/components/ui/segmented-control";
import { Select, SelectContent, SelectItem, SelectSeparator, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import {
  isEnumValue,
  MEMORY_KIND_META,
  MEMORY_KINDS,
  MEMORY_SCOPE_META,
  MEMORY_SCOPES,
  MEMORY_STATUS_META,
  MEMORY_STATUSES,
  type MemoryKind,
  type MemoryScope,
  type MemoryStatus,
} from "@/lib/enums";
import { formatNumber } from "@/lib/format";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

import type { StatusCounts } from "./use-memory-data";
import type { MemoryUrlPatch, MemoryUrlState } from "./use-memory-url-state";

const SCOPE_OPTIONS: ReadonlyArray<SegmentedOption<MemoryScope | "all">> = [
  { value: "all", label: "Toutes" },
  ...MEMORY_SCOPES.map((scope) => ({ value: scope, label: MEMORY_SCOPE_META[scope].label })),
];

export interface MemoryFiltersProps {
  state: MemoryUrlState;
  onChange: (patch: MemoryUrlPatch) => void;
  counts: StatusCounts;
  className?: string;
}

function CountLabel({ value }: { value: number | undefined }) {
  return (
    <span className="ml-1.5 rounded bg-muted px-1.5 py-px text-[11px] font-medium tabular-nums text-muted-foreground">
      {typeof value === "number" ? formatNumber(value, 0) : "…"}
    </span>
  );
}

/** Search (debounced), scope, kinds, status (with counts) and history filters of the memory explorer. */
export function MemoryFilters({ state, onChange, counts, className }: MemoryFiltersProps) {
  const [search, setSearch] = React.useState(state.q);
  const debounced = useDebouncedValue(search, 300);
  const lastPushed = React.useRef(state.q);

  // Push the debounced search to the URL.
  React.useEffect(() => {
    if (debounced.trim() === lastPushed.current.trim()) return;
    lastPushed.current = debounced;
    onChange({ q: debounced });
  }, [debounced, onChange]);

  // Follow external URL changes (reset, back navigation).
  React.useEffect(() => {
    if (state.q.trim() !== lastPushed.current.trim()) {
      lastPushed.current = state.q;
      setSearch(state.q);
    }
  }, [state.q]);

  const toggleKind = (kind: MemoryKind) => {
    const next = state.kinds.includes(kind) ? state.kinds.filter((k) => k !== kind) : [...state.kinds, kind];
    // Selecting every kind is the same as no kind filter.
    onChange({ kinds: next.length === MEMORY_KINDS.length ? [] : next });
  };

  const hasFilters =
    state.scope !== "all" || state.status !== "all" || state.kinds.length > 0 || state.q.trim() !== "" || state.history || state.asOf !== "";

  const reset = () => {
    lastPushed.current = "";
    setSearch("");
    onChange({ scope: "all", status: "all", kinds: [], q: "", history: false, asOf: "" });
  };

  return (
    <div className={cn("grid gap-3 rounded-xl border border-border bg-card p-3 shadow-xs", className)}>
      <Input
        type="search"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Rechercher une décision, un besoin, un fait…"
        aria-label="Rechercher dans la mémoire"
        leftIcon={<Search aria-hidden />}
        rightSlot={
          search ? (
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={() => setSearch("")}
              aria-label="Effacer la recherche"
              className="size-6"
            >
              <X aria-hidden />
            </Button>
          ) : undefined
        }
      />

      <div className="-mx-1 overflow-x-auto px-1 pb-0.5">
        <SegmentedControl
          value={state.scope}
          onValueChange={(scope) => onChange({ scope })}
          options={SCOPE_OPTIONS}
          size="sm"
          fullWidth
          aria-label="Portée"
          className="min-w-max"
        />
      </div>

      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Nature">
        {MEMORY_KINDS.map((kind) => {
          const meta = MEMORY_KIND_META[kind];
          const active = state.kinds.includes(kind);
          return (
            <button
              key={kind}
              type="button"
              aria-pressed={active}
              onClick={() => toggleKind(kind)}
              className={cn(
                "inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium ring-1 ring-inset transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-3.5",
                active
                  ? toneClasses(meta.tone).soft
                  : "bg-background text-muted-foreground ring-border hover:bg-accent hover:text-foreground",
              )}
            >
              <EnumIcon name={meta.icon} />
              {meta.label}
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Select
          value={state.status}
          onValueChange={(v) => onChange({ status: isEnumValue(MEMORY_STATUSES, v) ? (v as MemoryStatus) : "all" })}
        >
          <SelectTrigger size="sm" className="w-full min-w-44 sm:w-56" aria-label="Statut">
            <SelectValue placeholder="Statut" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">
              Tous les statuts
              <CountLabel value={counts.total} />
            </SelectItem>
            <SelectSeparator />
            {MEMORY_STATUSES.map((status) => {
              const meta = MEMORY_STATUS_META[status];
              return (
                <SelectItem
                  key={status}
                  value={status}
                  icon={<span className={cn("size-2 rounded-full", toneClasses(meta.tone).dot)} aria-hidden />}
                >
                  {meta.label}
                  <CountLabel value={counts.byStatus[status]} />
                </SelectItem>
              );
            })}
          </SelectContent>
        </Select>

        <div className="flex items-center gap-2">
          <Switch
            id="memory-history"
            size="sm"
            checked={state.history}
            onCheckedChange={(checked) => onChange({ history: checked })}
          />
          <Label htmlFor="memory-history" className="cursor-pointer text-xs font-normal text-muted-foreground">
            Afficher l&apos;historique
          </Label>
        </div>

        <div className="flex items-center gap-2">
          <Label htmlFor="memory-as-of" className="text-xs font-normal text-muted-foreground">
            Telle que connue au
          </Label>
          <Input
            id="memory-as-of"
            type="date"
            className="h-8 w-[150px] text-xs"
            value={state.asOf}
            onChange={(e) => onChange({ asOf: e.target.value })}
            title="Versions connues et valides à cette date"
          />
        </div>

        {hasFilters ? (
          <Button variant="ghost" size="xs" onClick={reset} leftIcon={<FilterX aria-hidden />} className="ml-auto">
            Réinitialiser
          </Button>
        ) : null}
      </div>
    </div>
  );
}
