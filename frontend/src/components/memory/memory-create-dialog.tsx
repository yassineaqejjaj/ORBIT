"use client";

import * as React from "react";
import { FilePlus2, Plus, Search, X } from "lucide-react";
import { toast } from "sonner";

import { ClassificationBanner } from "@/components/domain/classification-banner";
import { EnumIcon } from "@/components/domain/enum-icon";
import { SourceKindIcon } from "@/components/domain/source-kind-icon";
import { ClassificationSelect, classificationPayload, type ClassificationChoice } from "@/components/sources/classification-select";
import { TagsInput } from "@/components/sources/tags-input";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { errorMessage, isApiError } from "@/lib/api/client";
import { useCreateMemory, useDocuments, useMe } from "@/lib/api/hooks";
import type { DocumentSummary, MemoryIn, MemoryItem } from "@/lib/api/types";
import {
  MEMORY_KIND_META,
  MEMORY_KINDS,
  MEMORY_SCOPE_META,
  type MemoryKind,
  type MemoryScope,
} from "@/lib/enums";
import { formatDate } from "@/lib/format";

import { dateInputToIso, todayInput } from "./memory-dates";
import { CREATABLE_SCOPES } from "./memory-utils";

const KIND_OPTIONS = MEMORY_KINDS.map((kind) => ({
  value: kind,
  label: MEMORY_KIND_META[kind].label,
  icon: <EnumIcon name={MEMORY_KIND_META[kind].icon} />,
}));

const SCOPE_OPTIONS = CREATABLE_SCOPES.map((scope) => ({
  value: scope,
  label: MEMORY_SCOPE_META[scope].label,
  description: MEMORY_SCOPE_META[scope].description,
  icon: <EnumIcon name={MEMORY_SCOPE_META[scope].icon} />,
}));

interface PickedSource {
  document: Pick<DocumentSummary, "id" | "title" | "source_kind" | "source_name">;
  excerpt: string;
}

function DocumentPicker({
  slug,
  picked,
  onChange,
}: {
  slug: string;
  picked: PickedSource[];
  onChange: (next: PickedSource[]) => void;
}) {
  const [query, setQuery] = React.useState("");
  const q = useDebouncedValue(query.trim(), 250);
  const documents = useDocuments(slug, { q: q || undefined, status: "indexed", page_size: 6 }, { enabled: q.length >= 2 });
  const pickedIds = new Set(picked.map((p) => p.document.id));
  const results = (documents.data?.items ?? []).filter((d) => !pickedIds.has(d.id));

  return (
    <div className="grid gap-2">
      {picked.length > 0 ? (
        <ul className="grid gap-2">
          {picked.map((p, index) => (
            <li key={p.document.id} className="grid gap-2 rounded-lg border border-border bg-muted/30 p-2.5">
              <div className="flex items-center gap-2">
                <SourceKindIcon kind={p.document.source_kind} chip size="sm" />
                <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{p.document.title}</span>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  onClick={() => onChange(picked.filter((x) => x.document.id !== p.document.id))}
                  aria-label={`Retirer ${p.document.title}`}
                >
                  <X aria-hidden />
                </Button>
              </div>
              <Textarea
                value={p.excerpt}
                onChange={(e) => {
                  const next = [...picked];
                  next[index] = { ...p, excerpt: e.target.value };
                  onChange(next);
                }}
                rows={2}
                maxLength={4000}
                placeholder="Extrait justificatif (optionnel) — ex. le paragraphe du compte rendu"
                aria-label={`Extrait de ${p.document.title}`}
                className="text-[13px]"
              />
            </li>
          ))}
        </ul>
      ) : null}
      <Input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Rechercher un document source (2 caractères min.)…"
        aria-label="Rechercher un document source"
        leftIcon={<Search aria-hidden />}
        size="sm"
      />
      {q.length >= 2 ? (
        <div className="grid max-h-48 gap-1 overflow-y-auto rounded-lg border border-border p-1">
          {documents.isPending ? (
            Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-9 rounded-md" />)
          ) : documents.isError ? (
            <p className="px-2 py-1.5 text-xs text-destructive">{errorMessage(documents.error)}</p>
          ) : results.length === 0 ? (
            <p className="px-2 py-1.5 text-xs text-muted-foreground">Aucun document indexé ne correspond.</p>
          ) : (
            results.map((d) => (
              <button
                key={d.id}
                type="button"
                onClick={() => {
                  onChange([...picked, { document: d, excerpt: "" }]);
                  setQuery("");
                }}
                className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <SourceKindIcon kind={d.source_kind} size="sm" />
                <span className="min-w-0 flex-1 truncate text-[13px]">{d.title}</span>
                <span className="shrink-0 text-[11px] text-muted-foreground">
                  {d.source_name} · {formatDate(d.source_updated_at ?? d.updated_at)}
                </span>
                <Plus className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}

export interface MemoryCreateDialogProps {
  slug: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (item: MemoryItem) => void;
  /** Pre-selected scope (e.g. the active scope filter). */
  defaultScope?: MemoryScope;
}

/** "Nouvelle mémoire": scope, kind, title, content, classification, validity, provenance documents. */
export function MemoryCreateDialog({ slug, open, onOpenChange, onCreated, defaultScope }: MemoryCreateDialogProps) {
  const { data: me } = useMe();
  const [scope, setScope] = React.useState<MemoryScope>(defaultScope ?? "project");
  const [kind, setKind] = React.useState<MemoryKind>("decision");
  const [title, setTitle] = React.useState("");
  const [content, setContent] = React.useState("");
  const [classification, setClassification] = React.useState<ClassificationChoice>("auto");
  const [validFrom, setValidFrom] = React.useState(todayInput());
  const [validTo, setValidTo] = React.useState("");
  const [sessionId, setSessionId] = React.useState("");
  const [tags, setTags] = React.useState<string[]>([]);
  const [validated, setValidated] = React.useState(false);
  const [sources, setSources] = React.useState<PickedSource[]>([]);
  const [touched, setTouched] = React.useState(false);
  const create = useCreateMemory(slug, { meta: { silentError: true } });

  React.useEffect(() => {
    if (!open) return;
    setScope(defaultScope && defaultScope !== "short_term" ? defaultScope : "project");
    setKind("decision");
    setTitle("");
    setContent("");
    setClassification("auto");
    setValidFrom(todayInput());
    setValidTo("");
    setSessionId("");
    setTags([]);
    setValidated(false);
    setSources([]);
    setTouched(false);
    create.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const fieldErrors = isApiError(create.error) ? create.error.fieldErrors : {};
  const errors = {
    title: !title.trim() ? "Le titre est obligatoire." : fieldErrors.title,
    content: !content.trim() ? "Le contenu est obligatoire." : fieldErrors.content,
    sessionId: scope === "short_term" && !sessionId.trim() ? "L'identifiant de session est obligatoire." : fieldErrors.session_id,
    validTo: validTo && validFrom && validTo < validFrom ? "La fin de validité doit être postérieure au début." : fieldErrors.valid_to,
  };
  const invalid = Boolean(errors.title || errors.content || errors.sessionId || errors.validTo);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (invalid) return;
    const body: MemoryIn = {
      scope,
      kind,
      title: title.trim(),
      content: content.trim(),
      status: validated ? "validated" : "proposed",
    };
    const level = classificationPayload(classification);
    if (level !== undefined) body.classification = level;
    if (validFrom) body.valid_from = dateInputToIso(validFrom, "start");
    if (validTo) body.valid_to = dateInputToIso(validTo, "end");
    if (tags.length) body.tags = tags;
    if (scope === "user" && me) body.subject_user_id = me.id;
    if (scope === "short_term") body.session_id = sessionId.trim();
    if (sources.length) {
      body.provenance = sources.map((s) => ({
        document_id: s.document.id,
        source_label: s.document.source_name,
        ...(s.excerpt.trim() ? { excerpt: s.excerpt.trim() } : {}),
      }));
    }
    try {
      const item = await create.mutateAsync(body);
      toast.success("Élément mémoire créé", {
        description: `« ${item.title} » — ${item.status === "validated" ? "validé" : "proposé, en attente de validation"}.`,
      });
      onCreated(item);
      onOpenChange(false);
    } catch {
      // Rendered inline.
    }
  };

  const show = (error: string | undefined) => (touched ? error : undefined);

  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent size="lg">
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <DialogHeader>
            <DialogTitle>Nouvelle mémoire</DialogTitle>
            <DialogDescription>
              Ajoutez une décision, un besoin, une contrainte ou un fait. Il sera versionné, gouverné et servi aux agents
              selon ses droits d&apos;accès.
            </DialogDescription>
          </DialogHeader>

          {classification !== "auto" ? <ClassificationBanner level={classification} compact context="ingest" /> : null}

          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              id="memory-new-scope"
              label="Portée"
              hint={scope === "user" ? "Visible uniquement de vous (et des agents agissant pour vous)." : undefined}
            >
              <SimpleSelect<MemoryScope> id="memory-new-scope" value={scope} onValueChange={setScope} options={SCOPE_OPTIONS} />
            </Field>
            <Field id="memory-new-kind" label="Nature">
              <SimpleSelect<MemoryKind> id="memory-new-kind" value={kind} onValueChange={setKind} options={KIND_OPTIONS} />
            </Field>
          </div>

          {scope === "short_term" ? (
            <Field
              id="memory-new-session"
              label="Identifiant de session"
              required
              hint="La mémoire court terme expire selon la durée configurée pour le projet."
              error={show(errors.sessionId)}
            >
              <Input
                id="memory-new-session"
                value={sessionId}
                onChange={(e) => setSessionId(e.target.value)}
                placeholder="ex. atlas-spec-redaction"
                maxLength={200}
              />
            </Field>
          ) : null}

          <Field id="memory-new-title" label="Titre" required error={show(errors.title)}>
            <Input
              id="memory-new-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="ex. Décision : l'application sera une PWA"
              maxLength={300}
              autoFocus
            />
          </Field>

          <Field id="memory-new-content" label="Contenu" required hint="Markdown accepté." error={show(errors.content)}>
            <Textarea
              id="memory-new-content"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={5}
              maxLength={20000}
              placeholder="Contexte, justification, portée de la décision…"
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-3">
            <Field id="memory-new-classification" label="Classification">
              <ClassificationSelect
                id="memory-new-classification"
                value={classification}
                onChange={setClassification}
                allowAuto
                autoLabel="Automatique"
              />
            </Field>
            <Field id="memory-new-from" label="Valide à partir du">
              <Input id="memory-new-from" type="date" value={validFrom} onChange={(e) => setValidFrom(e.target.value)} />
            </Field>
            <Field id="memory-new-to" label="Jusqu'au" error={show(errors.validTo)} hint="Optionnel">
              <Input
                id="memory-new-to"
                type="date"
                value={validTo}
                min={validFrom || undefined}
                onChange={(e) => setValidTo(e.target.value)}
              />
            </Field>
          </div>

          <Field id="memory-new-tags" label="Étiquettes">
            <TagsInput id="memory-new-tags" value={tags} onChange={setTags} />
          </Field>

          <Field
            id="memory-new-provenance"
            label="Provenance"
            hint="Optionnel — rattachez les documents qui justifient cet élément (traçabilité jusqu'à la source)."
          >
            <DocumentPicker slug={slug} picked={sources} onChange={setSources} />
          </Field>

          <div className="flex items-start gap-3 rounded-lg border border-border bg-muted/30 p-3">
            <Switch id="memory-new-validated" checked={validated} onCheckedChange={setValidated} className="mt-0.5" />
            <div className="grid gap-0.5">
              <Label htmlFor="memory-new-validated" className="cursor-pointer">
                Valider immédiatement
              </Label>
              <p className="text-xs text-muted-foreground">
                Sinon l&apos;élément est créé au statut « Proposé » et devra être validé avant d&apos;être servi en priorité.
              </p>
            </div>
          </div>

          {create.isError ? (
            <Alert tone="red" title="La création a échoué">
              {errorMessage(create.error)}
            </Alert>
          ) : null}

          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={create.isPending}>
              Annuler
            </Button>
            <Button type="submit" loading={create.isPending} disabled={touched && invalid} leftIcon={<FilePlus2 aria-hidden />}>
              Créer l&apos;élément
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
