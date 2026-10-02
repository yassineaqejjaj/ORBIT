"use client";

import * as React from "react";
import Link from "next/link";
import { Check, CopyCheck, ExternalLink, FileText, Keyboard, ListChecks, Merge, Sparkles, X } from "lucide-react";
import { toast } from "sonner";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { MemoryKindBadge } from "@/components/domain/memory-kind-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { projectHref } from "@/components/layout/nav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Kbd } from "@/components/ui/kbd";
import { Pagination } from "@/components/ui/pagination";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useHotkey } from "@/hooks/use-hotkey";
import { errorMessage } from "@/lib/api/client";
import {
  useBulkInbox,
  useInbox,
  type BulkAction,
  type BulkOut,
  type InboxItem,
  type InboxParams,
  type InboxSort,
} from "@/lib/api/features-feed";
import { useMemory } from "@/lib/api/hooks";
import { MEMORY_KIND_META, MEMORY_KINDS, type MemoryKind } from "@/lib/enums";
import { formatPercent, plural, truncate } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;
const ALL = "all";

const CONFIDENCE_OPTIONS = [
  { value: ALL, label: "Toute confiance" },
  { value: "0.5", label: "≥ 50 %" },
  { value: "0.7", label: "≥ 70 %" },
  { value: "0.85", label: "≥ 85 %" },
] as const;

function reportBulk(action: BulkAction, result: BulkOut) {
  const verb = { validate: "validé(s)", reject: "rejeté(s)", merge: "fusionné(s)" }[action];
  if (result.failed.length === 0) {
    toast.success(`${result.processed} item(s) ${verb}`);
    return;
  }
  toast.warning(`${result.processed} item(s) ${verb}, ${result.failed.length} échec(s)`, {
    description: result.failed
      .slice(0, 3)
      .map((f) => f.detail)
      .join(" · "),
  });
}

export function ProposalsPanel({ slug, active }: { slug: string; active: boolean }) {
  const [sort, setSort] = React.useState<InboxSort>("impact");
  const [kind, setKind] = React.useState<string>(ALL);
  const [minConfidence, setMinConfidence] = React.useState<string>(ALL);
  const [page, setPage] = React.useState(1);
  const params: InboxParams = {
    sort,
    kind: kind === ALL ? undefined : (kind as MemoryKind),
    min_confidence: minConfidence === ALL ? undefined : Number(minConfidence),
    page,
    page_size: PAGE_SIZE,
  };
  const inbox = useInbox(slug, params);
  const bulk = useBulkInbox(slug);
  const items = React.useMemo(() => inbox.data?.items ?? [], [inbox.data]);

  const [focusId, setFocusId] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [rejectIds, setRejectIds] = React.useState<string[] | null>(null);
  const [mergeIds, setMergeIds] = React.useState<string[] | null>(null);
  const rowRefs = React.useRef(new Map<string, HTMLLIElement>());

  // Keep focus and selection consistent with the current page.
  React.useEffect(() => {
    if (!items.length) {
      setFocusId(null);
      return;
    }
    if (!focusId || !items.some((i) => i.id === focusId)) setFocusId(items[0]?.id ?? null);
    setSelected((prev) => {
      const ids = new Set(items.map((i) => i.id));
      const next = new Set([...prev].filter((id) => ids.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [items, focusId]);

  React.useEffect(() => {
    setPage(1);
  }, [sort, kind, minConfidence]);

  const focusIndex = items.findIndex((i) => i.id === focusId);
  const focused = (focusIndex >= 0 ? items[focusIndex] : null) ?? null;
  const targets = selected.size ? [...selected] : focused ? [focused.id] : [];

  const move = (delta: number) => {
    if (!items.length) return;
    const index = Math.min(items.length - 1, Math.max(0, (focusIndex < 0 ? 0 : focusIndex) + delta));
    const id = items[index]?.id;
    if (!id) return;
    setFocusId(id);
    rowRefs.current.get(id)?.scrollIntoView({ block: "nearest" });
  };
  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const run = (action: BulkAction, ids: string[], extra: { into_id?: string; reason?: string } = {}) =>
    bulk.mutateAsync({ action, ids, ...extra }).then((result) => {
      reportBulk(action, result);
      setSelected(new Set());
      return result;
    });

  const busy = bulk.isPending;
  const hotkeys = active && !busy && rejectIds === null && mergeIds === null;
  useHotkey("j", () => move(1), { enabled: hotkeys });
  useHotkey("k", () => move(-1), { enabled: hotkeys });
  useHotkey("x", () => focused && toggle(focused.id), { enabled: hotkeys });
  useHotkey("v", () => targets.length && void run("validate", targets).catch(() => undefined), { enabled: hotkeys });
  useHotkey("r", () => targets.length && setRejectIds(targets), { enabled: hotkeys });
  useHotkey("m", () => openMerge(), { enabled: hotkeys });

  function openMerge() {
    const ids = selected.size >= 2 ? [...selected] : focused?.similar ? [focused.id] : [];
    if (selected.size < 2 && !focused?.similar) {
      toast.info("Fusion", { description: "Sélectionnez au moins deux propositions (touche x) pour les fusionner." });
      return;
    }
    setMergeIds(ids);
  }

  const allSelected = items.length > 0 && items.every((i) => selected.has(i.id));

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <SegmentedControl<InboxSort>
          size="sm"
          value={sort}
          onValueChange={setSort}
          aria-label="Trier les propositions"
          options={[
            { value: "impact", label: "Impact" },
            { value: "confidence", label: "Confiance" },
            { value: "recent", label: "Récentes" },
          ]}
        />
        <SimpleSelect
          size="sm"
          value={kind}
          onValueChange={setKind}
          aria-label="Type d'item"
          className="w-44"
          options={[
            { value: ALL, label: "Tous les types" },
            ...MEMORY_KINDS.map((k) => ({ value: k, label: MEMORY_KIND_META[k].label })),
          ]}
        />
        <SimpleSelect
          size="sm"
          value={minConfidence}
          onValueChange={setMinConfidence}
          aria-label="Confiance minimale"
          className="w-40"
          options={CONFIDENCE_OPTIONS}
        />
        <p className="ml-auto hidden items-center gap-1.5 text-xs text-muted-foreground md:flex">
          <Keyboard className="size-3.5" aria-hidden />
          <Kbd>j</Kbd>/<Kbd>k</Kbd> naviguer · <Kbd>x</Kbd> sélectionner · <Kbd>v</Kbd> valider · <Kbd>r</Kbd> rejeter ·{" "}
          <Kbd>m</Kbd> fusionner
        </p>
      </div>

      {selected.size > 0 ? (
        <div
          role="toolbar"
          aria-label="Actions groupées"
          className="sticky top-2 z-10 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 shadow-sm"
        >
          <span className="text-[13px] font-medium">{plural(selected.size, "proposition sélectionnée", "propositions sélectionnées")}</span>
          <div className="ml-auto flex flex-wrap gap-2">
            <Button size="sm" onClick={() => void run("validate", [...selected]).catch(() => undefined)} disabled={busy}>
              <Check aria-hidden />
              Valider
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setRejectIds([...selected])} disabled={busy}>
              <X aria-hidden />
              Rejeter
            </Button>
            <Button size="sm" variant="secondary" onClick={openMerge} disabled={busy || selected.size < 2}>
              <Merge aria-hidden />
              Fusionner
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
              Désélectionner
            </Button>
          </div>
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <div className="grid min-w-0 content-start gap-3">
          {inbox.isPending ? (
            <ul className="grid gap-2" aria-busy="true" aria-label="Chargement des propositions">
              {Array.from({ length: 5 }, (_, i) => (
                <Skeleton key={i} className="h-20 rounded-lg" />
              ))}
            </ul>
          ) : inbox.isError ? (
            <ErrorState error={inbox.error} onRetry={() => void inbox.refetch()} />
          ) : items.length === 0 ? (
            <EmptyState
              icon={<CopyCheck />}
              title="Aucune proposition à trier"
              description="Les items extraits des sources ou proposés par les agents apparaîtront ici avant validation."
            />
          ) : (
            <>
              <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
                <Checkbox
                  aria-label="Tout sélectionner sur la page"
                  checked={allSelected ? true : selected.size ? "indeterminate" : false}
                  onCheckedChange={(checked) => setSelected(checked === true ? new Set(items.map((i) => i.id)) : new Set())}
                />
                <span>{plural(inbox.data?.total ?? 0, "proposition", "propositions")}</span>
              </div>
              <ul className="grid gap-2" role="listbox" aria-label="Propositions" aria-multiselectable="true">
                {items.map((item) => (
                  <ProposalRow
                    key={item.id}
                    item={item}
                    focused={item.id === focusId}
                    selected={selected.has(item.id)}
                    onFocus={() => setFocusId(item.id)}
                    onToggle={() => toggle(item.id)}
                    ref={(node) => {
                      if (node) rowRefs.current.set(item.id, node);
                      else rowRefs.current.delete(item.id);
                    }}
                  />
                ))}
              </ul>
              <Pagination
                page={page}
                pageSize={PAGE_SIZE}
                total={inbox.data?.total ?? 0}
                onPageChange={setPage}
                disabled={inbox.isFetching}
              />
            </>
          )}
        </div>
        <ProposalPreview
          slug={slug}
          item={focused}
          busy={busy}
          onValidate={(id) => void run("validate", [id]).catch(() => undefined)}
          onReject={(id) => setRejectIds([id])}
          onMergeSimilar={(item) => setMergeIds([item.id])}
        />
      </div>

      <ConfirmDialog
        open={rejectIds !== null}
        onOpenChange={(open) => !open && setRejectIds(null)}
        title={rejectIds && rejectIds.length > 1 ? `Rejeter ${rejectIds.length} propositions ?` : "Rejeter la proposition ?"}
        description="Les items rejetés passent au statut « obsolète » (motif « Rejeté au tri ») et ne sont plus servis aux agents. Ils restent restaurables depuis la mémoire."
        confirmLabel="Rejeter"
        destructive
        reason="optional"
        reasonPlaceholder="Motif (facultatif)"
        loading={busy}
        onConfirm={(reason) =>
          run("reject", rejectIds ?? [], reason ? { reason } : {})
            .then(() => setRejectIds(null))
            .catch(() => undefined)
        }
      />
      <MergeDialog
        ids={mergeIds}
        items={items}
        busy={busy}
        onClose={() => setMergeIds(null)}
        onMerge={(ids, intoId) =>
          run("merge", ids, { into_id: intoId })
            .then(() => setMergeIds(null))
            .catch((error) => toast.error("Fusion impossible", { description: errorMessage(error) }))
        }
      />
    </div>
  );
}

const ProposalRow = React.forwardRef<
  HTMLLIElement,
  { item: InboxItem; focused: boolean; selected: boolean; onFocus: () => void; onToggle: () => void }
>(function ProposalRow({ item, focused, selected, onFocus, onToggle }, ref) {
  return (
    <li
      ref={ref}
      role="option"
      aria-selected={selected}
      aria-current={focused ? "true" : undefined}
      onClick={onFocus}
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-lg border bg-card px-3 py-2.5 transition-colors",
        focused ? "border-brand ring-1 ring-brand/40" : "border-border hover:bg-accent/40",
        selected && "bg-brand-soft/40",
      )}
    >
      <Checkbox
        className="mt-0.5"
        checked={selected}
        aria-label={`Sélectionner « ${item.title} »`}
        onClick={(e) => e.stopPropagation()}
        onCheckedChange={onToggle}
      />
      <div className="grid min-w-0 flex-1 gap-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <MemoryKindBadge kind={item.kind} />
          <ClassificationBadge level={item.classification} showLabel={false} />
          <p className="min-w-0 truncate text-[13px] font-medium text-foreground">{item.title}</p>
        </div>
        <p className="line-clamp-2 text-xs text-muted-foreground">{truncate(item.content, 220)}</p>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-muted-foreground">
          <span>Confiance {formatPercent(item.confidence)}</span>
          <span title="Contextes (30 j) où l'item était candidat">
            Impact {item.impact} contexte{item.impact > 1 ? "s" : ""}
          </span>
          {item.would_be_included > 0 ? (
            <span className="text-amber-700 dark:text-amber-300">
              {item.would_be_included} exclusion(s) évitable(s) si validé
            </span>
          ) : null}
          {item.similar ? (
            <Badge tone="violet" size="sm" icon={<Sparkles />}>
              Doublon probable · {formatPercent(item.similar.score)}
            </Badge>
          ) : null}
          <RelativeTime date={item.created_at} />
        </div>
      </div>
    </li>
  );
});

function ProposalPreview({
  slug,
  item,
  busy,
  onValidate,
  onReject,
  onMergeSimilar,
}: {
  slug: string;
  item: InboxItem | null;
  busy: boolean;
  onValidate: (id: string) => void;
  onReject: (id: string) => void;
  onMergeSimilar: (item: InboxItem) => void;
}) {
  const detail = useMemory(slug, item?.id);
  if (!item) {
    return (
      <Card className="hidden lg:block">
        <CardContent className="py-10">
          <EmptyState size="sm" variant="plain" icon={<ListChecks />} title="Aperçu" description="Sélectionnez une proposition." />
        </CardContent>
      </Card>
    );
  }
  const provenance = detail.data?.provenance ?? [];
  return (
    <Card className="h-fit lg:sticky lg:top-4" aria-label="Aperçu de la proposition">
      <CardHeader className="gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <MemoryKindBadge kind={item.kind} />
          <ClassificationBadge level={item.classification} />
        </div>
        <CardTitle className="text-[15px] leading-snug">{item.title}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-foreground">{item.content}</p>
        <dl className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-md bg-muted/60 px-2.5 py-2">
            <dt className="text-muted-foreground">Confiance</dt>
            <dd className="font-medium tabular-nums">{formatPercent(item.confidence)}</dd>
          </div>
          <div className="rounded-md bg-muted/60 px-2.5 py-2">
            <dt className="text-muted-foreground">Impact (30 j)</dt>
            <dd className="font-medium tabular-nums">{plural(item.impact, "contexte", "contextes")}</dd>
          </div>
        </dl>
        {item.similar ? (
          <div className="grid gap-2 rounded-lg border border-violet-300/60 bg-violet-50 px-3 py-2.5 text-[13px] dark:border-violet-400/30 dark:bg-violet-400/10">
            <p>
              Doublon probable de <strong className="font-medium">« {item.similar.title} »</strong> (
              {formatPercent(item.similar.score)})
            </p>
            <Button size="xs" variant="secondary" className="w-fit" onClick={() => onMergeSimilar(item)} disabled={busy}>
              <Merge aria-hidden />
              Fusionner dans cet item
            </Button>
          </div>
        ) : null}
        <div className="grid gap-1.5">
          <p className="text-xs font-medium text-muted-foreground">Provenance</p>
          {detail.isPending ? (
            <Skeleton className="h-10" />
          ) : provenance.length === 0 ? (
            <p className="text-xs text-muted-foreground">Aucune source rattachée.</p>
          ) : (
            <ul className="grid gap-1.5">
              {provenance.slice(0, 5).map((p) => (
                <li key={p.id} className="flex items-start gap-2 rounded-md border border-border px-2.5 py-2 text-xs">
                  <FileText className="mt-px size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                  <div className="grid min-w-0 gap-0.5">
                    <span className="truncate font-medium">{p.document_title ?? (p.source_label || "Source")}</span>
                    {p.excerpt ? <span className="line-clamp-2 text-muted-foreground">{p.excerpt}</span> : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="flex flex-wrap gap-2 border-t border-border pt-3">
          <Button size="sm" onClick={() => onValidate(item.id)} disabled={busy}>
            <Check aria-hidden />
            Valider <Kbd className="ml-1">v</Kbd>
          </Button>
          <Button size="sm" variant="secondary" onClick={() => onReject(item.id)} disabled={busy}>
            <X aria-hidden />
            Rejeter <Kbd className="ml-1">r</Kbd>
          </Button>
          <Button size="sm" variant="ghost" asChild>
            <Link href={`${projectHref(slug, "memory")}?item=${encodeURIComponent(item.id)}`}>
              <ExternalLink aria-hidden />
              Ouvrir
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/** Choose the item that is kept: the others' provenance is copied into it, then they become obsolete. */
function MergeDialog({
  ids,
  items,
  busy,
  onClose,
  onMerge,
}: {
  ids: string[] | null;
  items: InboxItem[];
  busy: boolean;
  onClose: () => void;
  onMerge: (ids: string[], intoId: string) => void;
}) {
  // A single id means "merge this proposal into its probable duplicate".
  const candidates = React.useMemo(() => {
    if (!ids) return [];
    if (ids.length === 1) {
      const item = items.find((i) => i.id === ids[0]);
      return item?.similar
        ? [
            { id: item.similar.id, title: `${item.similar.title} (doublon probable)` },
            { id: item.id, title: item.title },
          ]
        : [];
    }
    return ids.map((id) => ({ id, title: items.find((i) => i.id === id)?.title ?? id }));
  }, [ids, items]);
  const [intoId, setIntoId] = React.useState<string | null>(null);
  React.useEffect(() => setIntoId(candidates[0]?.id ?? null), [candidates]);

  return (
    <Dialog open={ids !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Fusionner des propositions</DialogTitle>
          <DialogDescription>
            Choisissez l&apos;item conservé : la provenance des autres lui est rattachée, puis ils passent au statut
            « obsolète » (« Fusionné dans … »).
          </DialogDescription>
        </DialogHeader>
        <fieldset className="grid gap-2">
          <legend className="sr-only">Item conservé</legend>
          {candidates.map((c) => (
            <label
              key={c.id}
              className={cn(
                "flex cursor-pointer items-center gap-2.5 rounded-lg border px-3 py-2 text-[13px]",
                intoId === c.id ? "border-brand bg-brand-soft/40" : "border-border hover:bg-accent/40",
              )}
            >
              <input
                type="radio"
                name="merge-into"
                className="accent-[var(--brand)]"
                checked={intoId === c.id}
                onChange={() => setIntoId(c.id)}
              />
              <span className="truncate">{c.title}</span>
            </label>
          ))}
        </fieldset>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>
            Annuler
          </Button>
          <Button
            disabled={!intoId || busy || candidates.length < 2}
            onClick={() => intoId && onMerge(candidates.map((c) => c.id).filter((id) => id !== intoId), intoId)}
          >
            <Merge aria-hidden />
            Fusionner
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
