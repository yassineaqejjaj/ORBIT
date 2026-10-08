"use client";

import * as React from "react";
import { FileAudio, FileText, Mic, Upload, X } from "lucide-react";
import { toast } from "sonner";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { errorMessage } from "@/lib/api/client";
import { useImportMeeting, useSources } from "@/lib/api/hooks";
import type { DocumentSummary } from "@/lib/api/types";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AUTO_CLASSIFICATION, ClassificationSelect, classificationPayload, type ClassificationChoice } from "./classification-select";
import { DEFAULT_SOURCE, SourceSelect, sourceIdPayload } from "./source-select";
import { TagsInput } from "./tags-input";

const TRANSCRIPT_EXTENSIONS = ["vtt", "srt", "docx", "txt", "md"];
const AUDIO_EXTENSIONS = ["mp3", "m4a", "mp4", "wav", "webm", "ogg", "flac"];
const ACCEPT = [...TRANSCRIPT_EXTENSIONS, ...AUDIO_EXTENSIONS].map((e) => `.${e}`).join(",");

function extensionOf(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i + 1).toLowerCase() : "";
}

function titleOf(name: string): string {
  const stem = name.includes(".") ? name.slice(0, name.lastIndexOf(".")) : name;
  return stem.replace(/[_-]+/g, " ").trim();
}

export interface MeetingDialogProps {
  slug: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultSourceId?: string;
  onCreated?: (doc: DocumentSummary) => void;
}

/** « Importer une réunion » (§F1): transcript (VTT, SRT, Teams/Meet DOCX, text) or audio, date and participants. */
export function MeetingDialog({ slug, open, onOpenChange, defaultSourceId, onCreated }: MeetingDialogProps) {
  const sources = useSources(slug, { enabled: open });
  const importer = useImportMeeting(slug, { meta: { silentError: true } });
  const inputRef = React.useRef<HTMLInputElement>(null);

  const [file, setFile] = React.useState<File | null>(null);
  const [title, setTitle] = React.useState("");
  const [date, setDate] = React.useState("");
  const [participants, setParticipants] = React.useState<string[]>([]);
  const [sourceId, setSourceId] = React.useState<string>(defaultSourceId ?? DEFAULT_SOURCE);
  const [classification, setClassification] = React.useState<ClassificationChoice>(AUTO_CLASSIFICATION);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setSourceId(defaultSourceId ?? DEFAULT_SOURCE);
      return;
    }
    setFile(null);
    setTitle("");
    setDate("");
    setParticipants([]);
    setClassification(AUTO_CLASSIFICATION);
    setError(null);
    importer.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only on open/close
  }, [open, defaultSourceId]);

  const pick = (files: FileList | null) => {
    const f = files?.[0];
    if (!f) return;
    const ext = extensionOf(f.name);
    if (!TRANSCRIPT_EXTENSIONS.includes(ext) && !AUDIO_EXTENSIONS.includes(ext)) {
      setError(`« ${f.name} » n'est ni une transcription (.vtt, .srt, .docx, .txt, .md) ni un fichier audio.`);
      return;
    }
    if (f.size === 0) {
      setError(`« ${f.name} » est vide.`);
      return;
    }
    setError(null);
    setFile(f);
    if (!title) setTitle(titleOf(f.name));
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!file) {
      setError("Choisissez une transcription ou un enregistrement audio.");
      return;
    }
    try {
      const doc = await importer.mutateAsync({
        file,
        title: title.trim() || undefined,
        meeting_date: date || undefined,
        participants,
        source_id: sourceIdPayload(sourceId),
        classification: classificationPayload(classification),
      });
      toast.success("Réunion importée", {
        description: "Locuteurs, horodatages, décisions et actions sont extraits par le pipeline.",
      });
      onOpenChange(false);
      onCreated?.(doc);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const busy = importer.isPending;
  const audio = file ? AUDIO_EXTENSIONS.includes(extensionOf(file.name)) : false;

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent size="lg">
        <form onSubmit={submit} className="grid gap-5" noValidate>
          <DialogHeader>
            <div className="mb-1 flex size-10 items-center justify-center rounded-lg border border-border bg-brand-soft text-brand">
              <Mic className="size-5" aria-hidden />
            </div>
            <DialogTitle>Importer une réunion</DialogTitle>
            <DialogDescription>
              Transcription Teams, Meet ou Zoom (VTT, SRT, DOCX, texte « Nom : propos ») ou enregistrement audio. Les
              locuteurs et horodatages sont conservés ; les décisions et actions sont extraites avec leur auteur.
            </DialogDescription>
          </DialogHeader>

          {error ? <Alert tone="red">{error}</Alert> : null}

          <div
            role="button"
            tabIndex={0}
            aria-label="Déposer une transcription ou un fichier audio, ou parcourir"
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                inputRef.current?.click();
              }
            }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              pick(e.dataTransfer.files);
            }}
            className={cn(
              "flex cursor-pointer items-center gap-4 rounded-xl border-2 border-dashed border-border-strong bg-muted/30 px-5 py-5",
              "transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            )}
          >
            <span className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-border bg-background text-brand shadow-xs">
              {audio ? <FileAudio className="size-5" aria-hidden /> : file ? <FileText className="size-5" aria-hidden /> : <Upload className="size-5" aria-hidden />}
            </span>
            <div className="grid min-w-0 flex-1 gap-0.5">
              {file ? (
                <>
                  <p className="truncate text-sm font-medium text-foreground">{file.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {extensionOf(file.name).toUpperCase()} · {formatBytes(file.size)}
                    {audio ? " · transcription audio (garde-fou de classification)" : ""}
                  </p>
                </>
              ) : (
                <>
                  <p className="text-sm font-medium text-foreground">Glissez-déposez une transcription ou un audio</p>
                  <p className="text-xs text-muted-foreground">
                    .vtt, .srt, .docx, .txt, .md — ou audio .mp3, .m4a, .wav (si la transcription est configurée)
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
              accept={ACCEPT}
              className="sr-only"
              tabIndex={-1}
              onChange={(e) => {
                pick(e.target.files);
                e.target.value = "";
              }}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="meeting-title" label="Titre">
              <Input id="meeting-title" value={title} onChange={(e) => setTitle(e.target.value)} disabled={busy} maxLength={500} />
            </Field>
            <Field id="meeting-date" label="Date de la réunion" hint="Sert à dater les échéances (« d'ici vendredi »).">
              <Input id="meeting-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} disabled={busy} />
            </Field>
            <Field id="meeting-participants" label="Participants" hint="Complète les locuteurs détectés." className="sm:col-span-2">
              <TagsInput
                id="meeting-participants"
                value={participants}
                onChange={setParticipants}
                placeholder="Ajouter un participant…"
                disabled={busy}
              />
            </Field>
            <Field id="meeting-source" label="Source">
              <SourceSelect
                id="meeting-source"
                sources={sources.data}
                loading={sources.isPending}
                value={sourceId}
                onChange={setSourceId}
                kinds={["note"]}
                defaultDescription="Source « Notes » par défaut (créée si besoin)"
                disabled={busy}
              />
            </Field>
            <Field id="meeting-classification" label="Classification">
              <ClassificationSelect
                id="meeting-classification"
                value={classification}
                onChange={setClassification}
                allowAuto
                disabled={busy}
              />
            </Field>
          </div>

          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
              Annuler
            </Button>
            <Button type="submit" loading={busy} disabled={!file} leftIcon={<Upload aria-hidden />}>
              {busy ? "Import en cours…" : "Importer la réunion"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
