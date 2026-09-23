import * as React from "react";

import { cn } from "@/lib/utils";
import { Label } from "./label";

export interface FieldProps {
  /** Id of the control; used for the label `htmlFor` and aria-describedby ids. */
  id: string;
  label?: React.ReactNode;
  /** Helper text under the control. */
  hint?: React.ReactNode;
  /** Error message (replaces the hint, announced to screen readers). */
  error?: React.ReactNode;
  required?: boolean;
  className?: string;
  /** Extra element aligned to the right of the label (e.g. a counter). */
  labelAside?: React.ReactNode;
  children: React.ReactNode;
}

/** Label + control + hint/error, with the aria wiring conventions used across ORBIT forms. */
export function Field({ id, label, hint, error, required, className, labelAside, children }: FieldProps) {
  return (
    <div className={cn("grid gap-1.5", className)}>
      {label || labelAside ? (
        <div className="flex items-center justify-between gap-2">
          {label ? (
            <Label htmlFor={id} required={required}>
              {label}
            </Label>
          ) : (
            <span />
          )}
          {labelAside ? <span className="text-xs text-muted-foreground">{labelAside}</span> : null}
        </div>
      ) : null}
      {children}
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-xs font-medium text-destructive">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

/** aria-describedby value matching <Field> ids. */
export function fieldDescribedBy(id: string, { error, hint }: { error?: unknown; hint?: unknown }): string | undefined {
  if (error) return `${id}-error`;
  if (hint) return `${id}-hint`;
  return undefined;
}
