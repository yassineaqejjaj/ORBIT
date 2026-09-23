"use client";

import * as React from "react";

import { Button } from "./button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./dialog";
import { Field } from "./field";
import { Input } from "./input";
import { Textarea } from "./textarea";

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Extra content between the description and the form (warnings, summaries). */
  children?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  /** Ask for a free-text reason (sent to the API: forget, obsolete…). */
  reason?: "required" | "optional" | false;
  reasonLabel?: string;
  reasonPlaceholder?: string;
  /** Require typing this exact phrase to enable the confirm button (irreversible actions). */
  confirmPhrase?: string;
  /** Called with the reason (empty string when not requested). Keep the dialog open while the promise is pending. */
  onConfirm: (reason: string) => void | Promise<unknown>;
  loading?: boolean;
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  confirmLabel = "Confirmer",
  cancelLabel = "Annuler",
  destructive = false,
  reason = false,
  reasonLabel = "Motif",
  reasonPlaceholder = "Expliquez la raison de cette action (journalisée dans l'audit)…",
  confirmPhrase,
  onConfirm,
  loading = false,
}: ConfirmDialogProps) {
  const [reasonText, setReasonText] = React.useState("");
  const [phrase, setPhrase] = React.useState("");
  const [pending, setPending] = React.useState(false);
  const busy = loading || pending;

  React.useEffect(() => {
    if (!open) {
      setReasonText("");
      setPhrase("");
    }
  }, [open]);

  const reasonMissing = reason === "required" && reasonText.trim().length < 3;
  const phraseMismatch = Boolean(confirmPhrase) && phrase.trim() !== confirmPhrase;
  const disabled = busy || reasonMissing || phraseMismatch;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (disabled) return;
    try {
      setPending(true);
      await onConfirm(reasonText.trim());
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent size="sm" role="alertdialog">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {description ? <DialogDescription>{description}</DialogDescription> : null}
          </DialogHeader>
          {children}
          {reason ? (
            <Field id="confirm-reason" label={reasonLabel} required={reason === "required"}>
              <Textarea
                id="confirm-reason"
                value={reasonText}
                onChange={(e) => setReasonText(e.target.value)}
                placeholder={reasonPlaceholder}
                rows={3}
                required={reason === "required"}
                autoFocus
              />
            </Field>
          ) : null}
          {confirmPhrase ? (
            <Field
              id="confirm-phrase"
              label={
                <>
                  Saisissez <span className="font-mono font-semibold">{confirmPhrase}</span> pour confirmer
                </>
              }
            >
              <Input
                id="confirm-phrase"
                value={phrase}
                onChange={(e) => setPhrase(e.target.value)}
                autoComplete="off"
                spellCheck={false}
              />
            </Field>
          ) : null}
          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
              {cancelLabel}
            </Button>
            <Button type="submit" variant={destructive ? "destructive" : "primary"} loading={busy} disabled={disabled}>
              {confirmLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
