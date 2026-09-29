"use client";

import * as React from "react";
import { Archive, CheckCircle2, Eraser, MoreHorizontal, Pencil, Replace, RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  useForgetMemory,
  useObsoleteMemory,
  useRestoreMemory,
  useValidateMemory,
} from "@/lib/api/hooks";
import type { MemoryItem } from "@/lib/api/types";
import { truncate } from "@/lib/format";

import { MemoryEditDialog } from "./memory-edit-dialog";
import { MemorySupersedeDialog } from "./memory-supersede-dialog";
import { availableActions, type MemoryPermissions } from "./memory-utils";

type DialogKind = "obsolete" | "edit" | "supersede" | "restore" | "forget" | null;

export interface MemoryActionsProps {
  slug: string;
  item: MemoryItem;
  permissions: MemoryPermissions;
  /** Called with the item id to display after an action (actions may create a new version). */
  onItemChanged: (id: string) => void;
}

/** Lifecycle actions of a memory item (validate, obsolete, edit, supersede, restore, forget). */
export function MemoryActions({ slug, item, permissions, onItemChanged }: MemoryActionsProps) {
  const [dialog, setDialog] = React.useState<DialogKind>(null);
  const can = availableActions(item, permissions);
  const validate = useValidateMemory(slug);
  const obsolete = useObsoleteMemory(slug);
  const restore = useRestoreMemory(slug);
  const forget = useForgetMemory(slug);

  const close = () => setDialog(null);
  const follow = (next: MemoryItem) => {
    if (next.id !== item.id) onItemChanged(next.id);
  };

  const onValidate = () => {
    validate.mutate(
      { id: item.id },
      {
        onSuccess: (next) => {
          toast.success("Élément validé", {
            description: "Il sera désormais servi en priorité aux agents.",
          });
          follow(next);
        },
      },
    );
  };

  const anyAction = can.validate || can.obsolete || can.edit || can.supersede || can.restore || can.forget;
  if (!anyAction) return null;

  const secondary = can.supersede || can.obsolete || can.forget;

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {can.validate ? (
          <Button size="sm" onClick={onValidate} loading={validate.isPending} leftIcon={<CheckCircle2 aria-hidden />}>
            Valider
          </Button>
        ) : null}
        {can.restore ? (
          <Button size="sm" variant="secondary" onClick={() => setDialog("restore")} leftIcon={<RotateCcw aria-hidden />}>
            Restaurer
          </Button>
        ) : null}
        {can.edit ? (
          <Button size="sm" variant="secondary" onClick={() => setDialog("edit")} leftIcon={<Pencil aria-hidden />}>
            Modifier
          </Button>
        ) : null}
        {can.obsolete ? (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setDialog("obsolete")}
            leftIcon={<Archive aria-hidden />}
            className="hidden sm:inline-flex"
          >
            Marquer obsolète
          </Button>
        ) : null}
        {secondary ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="icon-sm" variant="ghost" aria-label="Autres actions">
                <MoreHorizontal aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              {can.supersede ? (
                <DropdownMenuItem onSelect={() => setDialog("supersede")}>
                  <Replace aria-hidden />
                  Remplacer par…
                </DropdownMenuItem>
              ) : null}
              {can.obsolete ? (
                <DropdownMenuItem onSelect={() => setDialog("obsolete")} className="sm:hidden">
                  <Archive aria-hidden />
                  Marquer obsolète
                </DropdownMenuItem>
              ) : null}
              {can.forget ? (
                <>
                  {can.supersede || can.obsolete ? <DropdownMenuSeparator className={can.supersede ? undefined : "sm:hidden"} /> : null}
                  <DropdownMenuItem destructive onSelect={() => setDialog("forget")}>
                    <Eraser aria-hidden />
                    Oublier…
                  </DropdownMenuItem>
                </>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>

      {can.edit ? (
        <MemoryEditDialog
          slug={slug}
          item={item}
          open={dialog === "edit"}
          onOpenChange={(o) => setDialog(o ? "edit" : null)}
          onSaved={follow}
        />
      ) : null}

      {can.supersede ? (
        <MemorySupersedeDialog
          slug={slug}
          item={item}
          open={dialog === "supersede"}
          onOpenChange={(o) => setDialog(o ? "supersede" : null)}
          onDone={(superseded) => follow(superseded)}
        />
      ) : null}

      <ConfirmDialog
        open={dialog === "obsolete"}
        onOpenChange={(o) => setDialog(o ? "obsolete" : null)}
        title="Marquer comme obsolète"
        description={`« ${truncate(item.title, 90)} » ne sera plus servi aux agents. L'élément reste consultable et peut être restauré.`}
        reason="required"
        reasonLabel="Motif de l'obsolescence"
        reasonPlaceholder="Ex. : information dépassée depuis la sprint review 6"
        confirmLabel="Marquer obsolète"
        loading={obsolete.isPending}
        onConfirm={async (reason) => {
          try {
            const next = await obsolete.mutateAsync({ id: item.id, reason });
            toast.success("Élément marqué obsolète");
            close();
            follow(next);
          } catch {
            // Error toasted globally; keep the dialog open.
          }
        }}
      />

      <ConfirmDialog
        open={dialog === "restore"}
        onOpenChange={(o) => setDialog(o ? "restore" : null)}
        title="Restaurer l'élément"
        description={`« ${truncate(item.title, 90)} » redeviendra en vigueur et pourra de nouveau être servi aux agents.`}
        reason="optional"
        reasonLabel="Motif"
        reasonPlaceholder="Ex. : le remplacement était erroné"
        confirmLabel="Restaurer"
        loading={restore.isPending}
        onConfirm={async (reason) => {
          try {
            const next = await restore.mutateAsync({ id: item.id, reason: reason || undefined });
            toast.success("Élément restauré");
            close();
            follow(next);
          } catch {
            // Error toasted globally.
          }
        }}
      />

      <ConfirmDialog
        open={dialog === "forget"}
        onOpenChange={(o) => setDialog(o ? "forget" : null)}
        title="Oublier cet élément ?"
        description="Oubli sélectif (droit à l'effacement) : cette action est irréversible."
        destructive
        reason="required"
        reasonLabel="Justification de l'oubli"
        reasonPlaceholder="Ex. : information erronée, demande de la personne concernée…"
        confirmLabel="Oublier définitivement"
        loading={forget.isPending}
        onConfirm={async (reason) => {
          try {
            const next = await forget.mutateAsync({ id: item.id, reason });
            toast.success("Élément oublié", {
              description: "Le contenu a été effacé et l'oubli propagé aux éléments dérivés.",
            });
            close();
            follow(next);
          } catch {
            // Error toasted globally.
          }
        }}
      >
        <Alert tone="red" title="Ce qui va se passer">
          <ul className="mt-1 list-disc space-y-1 pl-4">
            <li>le contenu de toutes les versions est remplacé par « [oublié] » (titre et métadonnées conservés pour l&apos;audit) ;</li>
            <li>l&apos;élément est retiré de l&apos;index de recherche et ne sera plus jamais servi aux agents ;</li>
            <li>
              les éléments dérivés sont oubliés si toutes leurs sources le sont, sinon leur confiance est réduite ;
            </li>
            <li>les snapshots qui le citent le masquent et la mémoire court terme est purgée.</li>
          </ul>
        </Alert>
      </ConfirmDialog>
    </>
  );
}
