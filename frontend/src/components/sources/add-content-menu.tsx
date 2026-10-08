"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, FileSpreadsheet, Mic, NotebookPen, Plus, UploadCloud } from "lucide-react";

import { projectHref } from "@/components/layout/nav";
import { Button, type ButtonProps } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { DocumentSummary } from "@/lib/api/types";
import { ImportDialog } from "./import-dialog";
import { MeetingDialog } from "./meeting-dialog";
import { NoteDialog } from "./note-dialog";
import { UploadDialog } from "./upload-dialog";

type DialogKind = "upload" | "note" | "import" | "meeting" | null;

export interface AddContentMenuProps {
  slug: string;
  /** Trigger label (default "Ajouter"). */
  label?: string;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
  /** Preselected source for every dialog. */
  defaultSourceId?: string;
  align?: "start" | "end";
}

/** "Ajouter" menu → upload files, write a note, import a meeting or a JSON/CSV batch (editor+). */
export function AddContentMenu({
  slug,
  label = "Ajouter",
  variant = "primary",
  size = "md",
  defaultSourceId,
  align = "end",
}: AddContentMenuProps) {
  const router = useRouter();
  const [dialog, setDialog] = React.useState<DialogKind>(null);
  const setOpen = (kind: Exclude<DialogKind, null>) => (open: boolean) => setDialog(open ? kind : null);

  const openDocument = (doc: DocumentSummary) => {
    router.push(`${projectHref(slug, "sources")}/${encodeURIComponent(doc.id)}`);
  };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant={variant} size={size} leftIcon={<Plus aria-hidden />} rightIcon={<ChevronDown aria-hidden />}>
            {label}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align={align} className="w-72">
          <DropdownMenuLabel>Ingérer du contenu</DropdownMenuLabel>
          <DropdownMenuItem onSelect={() => setDialog("upload")} className="items-start py-2">
            <UploadCloud className="mt-0.5 text-brand" aria-hidden />
            <span className="grid gap-0.5">
              <span className="font-medium">Téléverser des fichiers</span>
              <span className="text-xs text-muted-foreground">PDF, DOCX, Markdown, HTML, texte</span>
            </span>
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setDialog("note")} className="items-start py-2">
            <NotebookPen className="mt-0.5 text-brand" aria-hidden />
            <span className="grid gap-0.5">
              <span className="font-medium">Nouvelle note</span>
              <span className="text-xs text-muted-foreground">Compte rendu, ticket, fiche CRM, retour…</span>
            </span>
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setDialog("meeting")} className="items-start py-2">
            <Mic className="mt-0.5 text-brand" aria-hidden />
            <span className="grid gap-0.5">
              <span className="font-medium">Importer une réunion</span>
              <span className="text-xs text-muted-foreground">Transcription VTT, SRT, DOCX, texte ou audio</span>
            </span>
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setDialog("import")} className="items-start py-2">
            <FileSpreadsheet className="mt-0.5 text-brand" aria-hidden />
            <span className="grid gap-0.5">
              <span className="font-medium">Importer (JSON / CSV)</span>
              <span className="text-xs text-muted-foreground">Un élément du fichier = un document</span>
            </span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <UploadDialog slug={slug} open={dialog === "upload"} onOpenChange={setOpen("upload")} defaultSourceId={defaultSourceId} />
      <NoteDialog
        slug={slug}
        open={dialog === "note"}
        onOpenChange={setOpen("note")}
        defaultSourceId={defaultSourceId}
        onCreated={openDocument}
      />
      <MeetingDialog
        slug={slug}
        open={dialog === "meeting"}
        onOpenChange={setOpen("meeting")}
        defaultSourceId={defaultSourceId}
        onCreated={openDocument}
      />
      <ImportDialog slug={slug} open={dialog === "import"} onOpenChange={setOpen("import")} defaultSourceId={defaultSourceId} />
    </>
  );
}
