"use client";

import * as React from "react";
import Link from "next/link";
import { CircleCheck, FileJson, FileSpreadsheet, FileUp, RefreshCw, Upload, X } from "lucide-react";
import { toast } from "sonner";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { SourceKindIcon } from "@/components/domain/source-kind-icon";
import { StatusBadge } from "@/components/domain/status-badge";
import { projectHref } from "@/components/layout/nav";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { errorMessage } from "@/lib/api/client";
import { useImportDocuments, useSources } from "@/lib/api/hooks";
import type { DocumentImportResult } from "@/lib/api/types";
import { SOURCE_KIND_META, type SourceKind } from "@/lib/enums";
import { formatBytes, formatNumber, plural } from "@/lib/format";
import { cn } from "@/lib/utils";
import { DEFAULT_SOURCE, SourceSelect, sourceIdPayload } from "./source-select";
import { IMPORT_KINDS, SourceKindSelect } from "./source-kind-select";

const IMPORT_MAX_BYTES = 20 * 1024 * 1024;
const RESULT_PREVIEW = 8;

const RECOGNIZED_COLUMNS: ReadonlyArray<[string, string]> = [
  ["Identifiant", "id, external_id"],
  ["Titre", "title, summary, subject, name"],
  ["Contenu", "content, description, body, text, notes"],
  ["Auteur", "author, reporter, owner"],
  ["Date métier", "updated_at, date, created"],
  ["Autres", "status, priority, tags/labels, classification, url/uri"],
];

function extensionOf(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i + 1).toLowerCase() : "";
}

export interface ImportDialogProps {
  slug: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultKind?: SourceKind;
  defaultSourceId?: string;
}

/** "Importer" — JSON array or CSV where each row becomes a document (tickets, CRM, feedback, traces). */
export function ImportDialog({ slug, open, onOpenChange, defaultKind = "ticket", defaultSourceId }: ImportDialogProps) {
  const sources = useSources(slug, { enabled: open });
  const importer = useImportDocuments(slug, { meta: { silentError: true } });
  const inputRef = React.useRef<HTMLInputElement>(null);

  const [file, setFile] = React.useState<File | null>(null);
  const [kind, setKind] = React.useState<SourceKind>(defaultKind);
  const [sourceId, setSourceId] = React.useState<string>(defaultSourceId ?? DEFAULT_SOURCE);
  const [dragging, setDragging] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<DocumentImportResult | null>(null);

  React.useEffect(() => {
    if (open) {
      setKind(defaultKind);
      setSourceId(defaultSourceId ?? DEFAULT_SOURCE);
      return;
    }
    setFile(null);
    setDragging(false);
    setError(null);
    setResult(null);
    importer.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only on open/close
  }, [open, defaultKind, defaultSourceId]);

  // A preselected source drives the kind (once its list is loaded).
  const syncedRef = React.useRef(false);
  React.useEffect(() => {
    if (!open) {
      syncedRef.current = false;
      return;
    }
    if (syncedRef.current || !defaultSourceId || !sources.data) return;
    syncedRef.current = true;
    const source = sources.data.find((s) => s.id === defaultSourceId);
    if (source && IMPORT_KINDS.includes(source.kind)) setKind(source.kind);
    else setSourceId(DEFAULT_SOURCE);
  }, [open, defaultSourceId, sources.data]);

  const changeKind = (next: SourceKind) => {
    setKind(next);
    const source = sources.data?.find((s) => s.id === sourceId);
    if (source && source.kind !== next) setSourceId(DEFAULT_SOURCE);
  };

  const pick = (files: FileList | null) => {
    const f = files?.[0];
    if (!f) return;
    const ext = extensionOf(f.name);
    if (ext !== "json" && ext !== "csv") {
      setError(`« ${f.name} » n'est pas un fichier JSON ou CSV.`);
      return;
    }
    if (f.size === 0) {
      setError(`« ${f.name} » est vide.`);
      return;
    }
    if (f.size > IMPORT_MAX_BYTES) {
      setError(`« ${f.name} » dépasse ${formatBytes(IMPORT_MAX_BYTES)}.`);
      return;
    }
    setError(null);
    setFile(f);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!file) {
      setError("Choisissez un fichier JSON ou CSV à importer.");
      return;
    }
    try {
      const res = await importer.mutateAsync({ file, source_kind: kind, source_id: sourceIdPayload(sourceId) });
      setResult(res);
      toast.success("Import terminé", {
        description: `${plural(res.created, "document créé", "documents créés")}, ${plural(res.updated, "mis à jour", "mis à jour")}.`,
      });
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const busy = importer.isPending;
  const ext = file ? extensionOf(file.name) : "";

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent size="lg">
        {result ? (
          <div className="grid gap-5">
            <DialogHeader>
              <div className="mb-1 flex size-10 items-center justify-center rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-400/25 dark:bg-emerald-400/10 dark:text-emerald-300">
                <CircleCheck className="size-5" aria-hidden />
              </div>
              <DialogTitle>Import terminé</DialogTitle>
              <DialogDescription>
                Les documents sont en cours de traitement par le pipeline (extraction, données personnelles, classification,
                indexation).
              </DialogDescription>
            </DialogHeader>
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-0.5 rounded-lg border border-border bg-background px-4 py-3">
                <span className="text-xs text-muted-foreground">Créés</span>
                <span className="text-2xl font-semibold tabular-nums text-foreground">{formatNumber(result.created, 0)}</span>
              </div>
              <div className="grid gap-0.5 rounded-lg border border-border bg-background px-4 py-3">
                <span className="text-xs text-muted-foreground">Mis à jour (nouvelle version)</span>
                <span className="text-2xl font-semibold tabular-nums text-foreground">{formatNumber(result.updated, 0)}</span>
              </div>
            </div>
            {result.documents.length > 0 ? (
              <ul className="grid max-h-64 gap-1 overflow-y-auto rounded-lg border border-border p-1">
                {result.documents.slice(0, RESULT_PREVIEW).map((doc) => (
                  <li key={doc.id}>
                    <Link
                      href={`${projectHref(slug, "sources")}/${encodeURIComponent(doc.id)}`}
                      onClick={() => onOpenChange(false)}
                      className="flex items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <SourceKindIcon kind={doc.source_kind} size="sm" />
                      <span className="min-w-0 flex-1 truncate text-[13px] text-foreground">{doc.title}</span>
                      {doc.current_version > 1 ? (
                        <span className="text-xs tabular-nums text-muted-foreground">v{doc.current_version}</span>
                      ) : null}
                      <ClassificationBadge level={doc.classification} showLabel={false} noTooltip />
                      <StatusBadge kind="document" status={doc.status} />
                    </Link>
                  </li>
                ))}
                {result.documents.length > RESULT_PREVIEW ? (
                  <li className="px-2 py-1.5 text-xs text-muted-foreground">
                    … et {plural(result.documents.length - RESULT_PREVIEW, "autre document", "autres documents")}
                  </li>
                ) : null}
              </ul>
            ) : null}
            <DialogFooter>
              <Button
                variant="secondary"
                leftIcon={<RefreshCw aria-hidden />}
                onClick={() => {
                  setResult(null);
                  setFile(null);
                  importer.reset();
                }}
              >
                Importer un autre fichier
              </Button>
              <Button onClick={() => onOpenChange(false)}>Terminer</Button>
            </DialogFooter>
          </div>
        ) : (
          <form onSubmit={submit} className="grid gap-5" noValidate>
            <DialogHeader>
              <div className="mb-1 flex size-10 items-center justify-center rounded-lg border border-border bg-brand-soft text-brand">
                <FileUp className="size-5" aria-hidden />
              </div>
              <DialogTitle>Importer des données (JSON ou CSV)</DialogTitle>
              <DialogDescription>
                Chaque ligne devient un document : tickets, comptes CRM, retours utilisateurs ou traces d&apos;agents. Un
                identifiant déjà connu crée une nouvelle version.
              </DialogDescription>
            </DialogHeader>

            {error ? <Alert tone="red">{error}</Alert> : null}

            <div
              role="button"
              tabIndex={0}
              aria-label="Déposer un fichier JSON ou CSV, ou parcourir"
              onClick={() => inputRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  inputRef.current?.click();
                }
              }}
              onDragOver={(e) => {
                e.preventDefault();
                if (!dragging) setDragging(true);
              }}
              onDragLeave={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
              }}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                pick(e.dataTransfer.files);
              }}
              className={cn(
                "flex cursor-pointer items-center gap-4 rounded-xl border-2 border-dashed px-5 py-5 transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                dragging ? "border-primary bg-brand-soft/60" : "border-border-strong bg-muted/30 hover:bg-muted/50",
              )}
            >
              <span className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-border bg-background text-brand shadow-xs">
                {ext === "csv" ? (
                  <FileSpreadsheet className="size-5" aria-hidden />
                ) : ext === "json" ? (
                  <FileJson className="size-5" aria-hidden />
                ) : (
                  <Upload className="size-5" aria-hidden />
                )}
              </span>
              <div className="grid min-w-0 flex-1 gap-0.5">
                {file ? (
                  <>
                    <p className="truncate text-sm font-medium text-foreground">{file.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {ext.toUpperCase()} · {formatBytes(file.size)}
                    </p>
                  </>
                ) : (
                  <>
                    <p className="text-sm font-medium text-foreground">
                      {dragging ? "Relâchez pour sélectionner le fichier" : "Glissez-déposez un fichier .json ou .csv"}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      ou <span className="font-medium text-primary">parcourez</span> — {formatBytes(IMPORT_MAX_BYTES)} maximum
                    </p>
                  </>
                )}
              </div>
              {file ? (
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    setFile(null);
                  }}
                  disabled={busy}
                  aria-label="Retirer le fichier"
                >
                  <X aria-hidden />
                </Button>
              ) : null}
              <input
                ref={inputRef}
                type="file"
                accept=".json,.csv,application/json,text/csv"
                className="sr-only"
                tabIndex={-1}
                onChange={(e) => {
                  pick(e.target.files);
                  e.target.value = "";
                }}
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field id="import-kind" label="Type de contenu" required hint="Un élément du fichier = un document de ce type.">
                <SourceKindSelect id="import-kind" value={kind} onChange={changeKind} kinds={IMPORT_KINDS} disabled={busy} />
              </Field>
              <Field id="import-source" label="Source">
                <SourceSelect
                  id="import-source"
                  sources={sources.data}
                  loading={sources.isPending}
                  value={sourceId}
                  onChange={setSourceId}
                  kinds={[kind]}
                  defaultDescription={`Source « ${SOURCE_KIND_META[kind].label} » par défaut (créée si besoin)`}
                  disabled={busy}
                />
              </Field>
            </div>

            <details className="group rounded-lg border border-border bg-muted/30 px-3.5 py-2.5 text-[13px]">
              <summary className="cursor-pointer select-none font-medium text-foreground marker:text-muted-foreground">
                Colonnes reconnues
              </summary>
              <dl className="mt-2 grid gap-1.5 sm:grid-cols-2">
                {RECOGNIZED_COLUMNS.map(([label, cols]) => (
                  <div key={label} className="grid gap-0.5">
                    <dt className="text-xs text-muted-foreground">{label}</dt>
                    <dd className="font-mono text-[12px] text-foreground">{cols}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-2 text-xs text-muted-foreground">Les autres colonnes sont conservées dans les métadonnées.</p>
            </details>

            <DialogFooter>
              <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
                Annuler
              </Button>
              <Button type="submit" loading={busy} disabled={!file} leftIcon={<Upload aria-hidden />}>
                {busy ? "Import en cours…" : "Importer"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
