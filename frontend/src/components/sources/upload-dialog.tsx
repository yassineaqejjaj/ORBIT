"use client";

import * as React from "react";
import { FileCode2, FileJson, FileSpreadsheet, FileText, FileType2, FileUp, UploadCloud, X } from "lucide-react";
import { toast } from "sonner";

import { ClassificationBanner } from "@/components/domain/classification-banner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { errorMessage } from "@/lib/api/client";
import { useSources, useUploadDocuments } from "@/lib/api/hooks";
import type { DocumentSummary } from "@/lib/api/types";
import { formatBytes, plural } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AclPicker } from "./acl-picker";
import { aclToPrincipals, DEFAULT_ACL_VALUE, isAclValid, type AclValue } from "./acl";
import { AUTO_CLASSIFICATION, ClassificationSelect, classificationPayload, type ClassificationChoice } from "./classification-select";
import { DEFAULT_SOURCE, SourceSelect, sourceIdPayload } from "./source-select";
import { TagsInput } from "./tags-input";

export const UPLOAD_MAX_BYTES = 50 * 1024 * 1024;
export const UPLOAD_EXTENSIONS = ["pdf", "docx", "md", "markdown", "txt", "html", "htm", "json", "csv"] as const;
const ACCEPT = UPLOAD_EXTENSIONS.map((e) => `.${e}`).join(",");

function extensionOf(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i + 1).toLowerCase() : "";
}

function FileIcon({ name }: { name: string }) {
  const ext = extensionOf(name);
  const cls = "size-4";
  if (ext === "pdf") return <FileType2 className={cn(cls, "text-red-600 dark:text-red-400")} aria-hidden />;
  if (ext === "json") return <FileJson className={cn(cls, "text-amber-600 dark:text-amber-400")} aria-hidden />;
  if (ext === "csv") return <FileSpreadsheet className={cn(cls, "text-emerald-600 dark:text-emerald-400")} aria-hidden />;
  if (ext === "html" || ext === "htm") return <FileCode2 className={cn(cls, "text-sky-600 dark:text-sky-400")} aria-hidden />;
  return <FileText className={cn(cls, "text-blue-600 dark:text-blue-400")} aria-hidden />;
}

interface Rejected {
  name: string;
  reason: string;
}

export interface UploadDialogProps {
  slug: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Preselected source id. */
  defaultSourceId?: string;
  onUploaded?: (documents: DocumentSummary[]) => void;
}

/** "Téléverser des fichiers" — drag & drop, classification, ACL presets, tags → POST /documents/upload. */
export function UploadDialog({ slug, open, onOpenChange, defaultSourceId, onUploaded }: UploadDialogProps) {
  const sources = useSources(slug, { enabled: open });
  const upload = useUploadDocuments(slug, { meta: { silentError: true } });
  const inputRef = React.useRef<HTMLInputElement>(null);

  const [files, setFiles] = React.useState<File[]>([]);
  const [rejected, setRejected] = React.useState<Rejected[]>([]);
  const [dragging, setDragging] = React.useState(false);
  const [sourceId, setSourceId] = React.useState<string>(defaultSourceId ?? DEFAULT_SOURCE);
  const [classification, setClassification] = React.useState<ClassificationChoice>(AUTO_CLASSIFICATION);
  const [acl, setAcl] = React.useState<AclValue>(DEFAULT_ACL_VALUE);
  const [tags, setTags] = React.useState<string[]>([]);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [aclError, setAclError] = React.useState<string | undefined>();

  React.useEffect(() => {
    if (open) {
      setSourceId(defaultSourceId ?? DEFAULT_SOURCE);
      return;
    }
    setFiles([]);
    setRejected([]);
    setDragging(false);
    setClassification(AUTO_CLASSIFICATION);
    setAcl(DEFAULT_ACL_VALUE);
    setTags([]);
    setFormError(null);
    setAclError(undefined);
    upload.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only on open/close
  }, [open, defaultSourceId]);

  const addFiles = (incoming: FileList | File[] | null) => {
    if (!incoming) return;
    const accepted: File[] = [];
    const refused: Rejected[] = [];
    for (const file of Array.from(incoming)) {
      const ext = extensionOf(file.name);
      if (!(UPLOAD_EXTENSIONS as readonly string[]).includes(ext)) {
        refused.push({ name: file.name, reason: "format non pris en charge" });
      } else if (file.size > UPLOAD_MAX_BYTES) {
        refused.push({ name: file.name, reason: `taille supérieure à ${formatBytes(UPLOAD_MAX_BYTES)}` });
      } else if (file.size === 0) {
        refused.push({ name: file.name, reason: "fichier vide" });
      } else {
        accepted.push(file);
      }
    }
    setFiles((prev) => {
      const keys = new Set(prev.map((f) => `${f.name}:${f.size}`));
      return [...prev, ...accepted.filter((f) => !keys.has(`${f.name}:${f.size}`))];
    });
    setRejected(refused);
    setFormError(null);
  };

  const totalSize = files.reduce((acc, f) => acc + f.size, 0);
  const level = classificationPayload(classification);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (files.length === 0) {
      setFormError("Ajoutez au moins un fichier à téléverser.");
      return;
    }
    if (!isAclValid(acl)) {
      setAclError("Sélectionnez au moins un membre autorisé.");
      return;
    }
    try {
      const docs = await upload.mutateAsync({
        files,
        source_id: sourceIdPayload(sourceId),
        classification: level,
        acl_principals: aclToPrincipals(acl),
        tags,
      });
      toast.success(`${plural(docs.length, "document")} envoyé${docs.length > 1 ? "s" : ""} au pipeline`, {
        description: "Extraction, détection des données personnelles, classification et indexation en cours.",
      });
      onUploaded?.(docs);
      onOpenChange(false);
    } catch (error) {
      setFormError(errorMessage(error));
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !upload.isPending && onOpenChange(o)}>
      <DialogContent size="lg">
        <form onSubmit={submit} className="grid gap-5" noValidate>
          <DialogHeader>
            <div className="mb-1 flex size-10 items-center justify-center rounded-lg border border-border bg-brand-soft text-brand">
              <FileUp className="size-5" aria-hidden />
            </div>
            <DialogTitle>Téléverser des fichiers</DialogTitle>
            <DialogDescription>
              PDF, DOCX, Markdown, texte, HTML, JSON ou CSV — {formatBytes(UPLOAD_MAX_BYTES)} maximum par fichier. Chaque
              fichier passe par le pipeline d&apos;ingestion complet.
            </DialogDescription>
          </DialogHeader>

          {formError ? <Alert tone="red">{formError}</Alert> : null}

          <div
            role="button"
            tabIndex={0}
            aria-label="Déposer des fichiers ou parcourir"
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                inputRef.current?.click();
              }
            }}
            onDragEnter={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragOver={(e) => {
              e.preventDefault();
              e.dataTransfer.dropEffect = "copy";
              if (!dragging) setDragging(true);
            }}
            onDragLeave={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
            }}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              addFiles(e.dataTransfer.files);
            }}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              dragging ? "border-primary bg-brand-soft/60" : "border-border-strong bg-muted/30 hover:bg-muted/50",
            )}
          >
            <span className="flex size-11 items-center justify-center rounded-xl border border-border bg-background text-brand shadow-xs">
              <UploadCloud className="size-5" aria-hidden />
            </span>
            <p className="text-sm font-medium text-foreground">
              {dragging ? "Relâchez pour ajouter les fichiers" : "Glissez-déposez vos fichiers ici"}
            </p>
            <p className="text-xs text-muted-foreground">
              ou <span className="font-medium text-primary underline-offset-2 hover:underline">parcourez votre ordinateur</span>
            </p>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept={ACCEPT}
              className="sr-only"
              tabIndex={-1}
              onChange={(e) => {
                addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>

          {rejected.length > 0 ? (
            <Alert tone="amber" title={`${plural(rejected.length, "fichier ignoré", "fichiers ignorés")}`}>
              <ul className="list-inside list-disc">
                {rejected.map((r) => (
                  <li key={r.name}>
                    <span className="font-medium">{r.name}</span> : {r.reason}
                  </li>
                ))}
              </ul>
            </Alert>
          ) : null}

          {files.length > 0 ? (
            <div className="grid gap-1.5">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>{plural(files.length, "fichier")} sélectionné{files.length > 1 ? "s" : ""}</span>
                <span className="tabular-nums">{formatBytes(totalSize)}</span>
              </div>
              <ul className="grid max-h-40 gap-1 overflow-y-auto rounded-lg border border-border p-1">
                {files.map((file) => (
                  <li key={`${file.name}:${file.size}`} className="flex items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-muted/60">
                    <FileIcon name={file.name} />
                    <span className="min-w-0 flex-1 truncate text-[13px] text-foreground">{file.name}</span>
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{formatBytes(file.size)}</span>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      onClick={() => setFiles((prev) => prev.filter((f) => f !== file))}
                      disabled={upload.isPending}
                      aria-label={`Retirer ${file.name}`}
                    >
                      <X aria-hidden />
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="upload-source" label="Source" hint="Les documents sont rattachés à cette source.">
              <SourceSelect
                id="upload-source"
                sources={sources.data}
                loading={sources.isPending}
                value={sourceId}
                onChange={setSourceId}
                defaultDescription="Source « Documents » par défaut du projet"
                disabled={upload.isPending}
              />
            </Field>
            <Field id="upload-classification" label="Classification" hint="Le pipeline peut relever le niveau (jamais l'abaisser).">
              <ClassificationSelect
                id="upload-classification"
                value={classification}
                onChange={setClassification}
                allowAuto
                disabled={upload.isPending}
              />
            </Field>
          </div>

          {level !== undefined && level >= 2 ? <ClassificationBanner level={level} context="ingest" compact /> : null}

          <Field id="upload-acl" label="Qui peut accéder à ces documents ?">
            <AclPicker
              slug={slug}
              value={acl}
              onChange={(v) => {
                setAcl(v);
                setAclError(undefined);
              }}
              error={aclError}
              disabled={upload.isPending}
              idPrefix="upload-acl"
            />
          </Field>

          <Field id="upload-tags" label="Étiquettes" hint="Entrée ou virgule pour valider une étiquette.">
            <TagsInput id="upload-tags" value={tags} onChange={setTags} disabled={upload.isPending} placeholder="spécification, pilote-lyon…" />
          </Field>

          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={upload.isPending}>
              Annuler
            </Button>
            <Button type="submit" loading={upload.isPending} disabled={files.length === 0} leftIcon={<UploadCloud aria-hidden />}>
              {upload.isPending
                ? "Téléversement…"
                : files.length > 1
                  ? `Téléverser ${files.length} fichiers`
                  : "Téléverser"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
