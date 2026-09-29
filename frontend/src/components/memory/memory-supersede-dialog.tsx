"use client";

import * as React from "react";
import { ArrowDown, Check, Replace, Search } from "lucide-react";
import { toast } from "sonner";

import { MemoryKindBadge } from "@/components/domain/memory-kind-badge";
import { ScopeBadge } from "@/components/domain/scope-badge";
import { StatusBadge } from "@/components/domain/status-badge";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { errorMessage } from "@/lib/api/client";
import { useMemoryList, useSupersedeMemory } from "@/lib/api/hooks";
import type { MemoryItem } from "@/lib/api/types";
import { formatDate, truncate } from "@/lib/format";
import { cn } from "@/lib/utils";

import { plainPreview } from "./memory-item-card";

export interface MemorySupersedeDialogProps {
  slug: string;
  item: MemoryItem;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called with the (new version of the) superseded item and the replacement. */
  onDone: (superseded: MemoryItem, replacement: MemoryItem) => void;
}

/** "Remplacer par…": pick the item that replaces the current one (search across current items). */
export function MemorySupersedeDialog({ slug, item, open, onOpenChange, onDone }: MemorySupersedeDialogProps) {
  const [query, setQuery] = React.useState("");
  const [selected, setSelected] = React.useState<MemoryItem | null>(null);
  const [reason, setReason] = React.useState("");
  const q = useDebouncedValue(query.trim(), 250);
  const supersede = useSupersedeMemory(slug, { meta: { silentError: true } });

  React.useEffect(() => {
    if (!open) return;
    setQuery("");
    setSelected(null);
    setReason("");
    supersede.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, item.id]);

  const results = useMemoryList(
    slug,
    { q: q || undefined, kind: q ? undefined : item.kind, page_size: 30 },
    { enabled: open && Boolean(slug) },
  );

  const candidates = React.useMemo(() => {
    const list = (results.data?.items ?? []).filter(
      (c) =>
        c.lineage_id !== item.lineage_id &&
        c.id !== item.id &&
        c.is_current &&
        (c.status === "validated" || c.status === "proposed"),
    );
    // Same kind first, then most recent.
    return list.sort((a, b) => {
      if ((a.kind === item.kind) !== (b.kind === item.kind)) return a.kind === item.kind ? -1 : 1;
      return new Date(b.valid_from).getTime() - new Date(a.valid_from).getTime();
    });
  }, [results.data, item]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected) return;
    try {
      const superseded = await supersede.mutateAsync({ id: item.id, by_id: selected.id, reason: reason.trim() || undefined });
      toast.success("Remplacement enregistré", {
        description: `« ${truncate(item.title, 60)} » est remplacé par « ${truncate(selected.title, 60)} ».`,
      });
      onDone(superseded, selected);
      onOpenChange(false);
    } catch {
      // Rendered inline.
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !supersede.isPending && onOpenChange(o)}>
      <DialogContent size="lg">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Remplacer par un autre élément</DialogTitle>
            <DialogDescription>
              L&apos;élément actuel passera au statut « Remplacé » : il ne sera plus servi aux agents (exclusion motivée
              « remplacé ») mais reste consultable et peut être restauré.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-2 rounded-lg border border-border bg-muted/40 p-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <MemoryKindBadge kind={item.kind} />
              <StatusBadge kind="memory" status={item.status} />
            </div>
            <p className="text-[13px] font-medium text-foreground">{item.title}</p>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <ArrowDown className="size-3.5" aria-hidden />
              sera remplacé par {selected ? <strong className="text-foreground">« {truncate(selected.title, 80)} »</strong> : "…"}
            </div>
          </div>

          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Rechercher l'élément de remplacement…"
            aria-label="Rechercher l'élément de remplacement"
            leftIcon={<Search aria-hidden />}
            autoFocus
          />

          <div
            role="radiogroup"
            aria-label="Élément de remplacement"
            className="grid max-h-72 gap-1.5 overflow-y-auto rounded-lg border border-border p-1.5"
          >
            {results.isPending ? (
              Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-14 rounded-md" />)
            ) : results.isError ? (
              <p className="p-3 text-[13px] text-destructive">{errorMessage(results.error)}</p>
            ) : candidates.length === 0 ? (
              <EmptyState
                variant="plain"
                size="sm"
                icon={<Search />}
                title="Aucun élément compatible"
                description={
                  q
                    ? "Aucun élément validé ou proposé ne correspond à cette recherche."
                    : "Recherchez un élément validé ou proposé qui remplace celui-ci."
                }
              />
            ) : (
              candidates.map((c) => {
                const active = selected?.id === c.id;
                return (
                  <button
                    key={c.id}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => setSelected(c)}
                    className={cn(
                      "grid gap-1 rounded-md border px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      active ? "border-brand/60 bg-brand-soft/50" : "border-transparent hover:bg-accent",
                    )}
                  >
                    <span className="flex items-center gap-1.5">
                      <MemoryKindBadge kind={c.kind} />
                      <ScopeBadge scope={c.scope} />
                      <StatusBadge kind="memory" status={c.status} />
                      <span className="ml-auto text-xs text-muted-foreground">{formatDate(c.valid_from)}</span>
                      {active ? <Check className="size-4 text-primary" aria-hidden /> : null}
                    </span>
                    <span className="text-[13px] font-medium text-foreground">{c.title}</span>
                    <span className="line-clamp-1 text-xs text-muted-foreground">{plainPreview(c.content)}</span>
                  </button>
                );
              })
            )}
          </div>

          <Field id="memory-supersede-reason" label="Motif" hint="Optionnel — journalisé dans l'historique et l'audit.">
            <Textarea
              id="memory-supersede-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
              maxLength={2000}
              placeholder="Ex. : décision revue en comité de pilotage du 12 septembre"
            />
          </Field>

          {supersede.isError ? (
            <Alert tone="red" title="Le remplacement a échoué">
              {errorMessage(supersede.error)}
            </Alert>
          ) : null}

          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={supersede.isPending}>
              Annuler
            </Button>
            <Button type="submit" loading={supersede.isPending} disabled={!selected} leftIcon={<Replace aria-hidden />}>
              Remplacer
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
