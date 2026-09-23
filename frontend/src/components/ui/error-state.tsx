"use client";

import * as React from "react";
import { CloudOff, FileQuestion, Lock, RefreshCw, ServerCrash } from "lucide-react";

import { errorMessage, isApiError } from "@/lib/api/client";
import { Button } from "./button";
import { EmptyState } from "./empty-state";

export interface ErrorStateProps {
  error: unknown;
  /** Retry callback (e.g. `query.refetch`). */
  onRetry?: () => void;
  title?: React.ReactNode;
  className?: string;
  size?: "sm" | "md" | "lg";
  variant?: "card" | "plain";
  /** Extra actions rendered next to the retry button. */
  action?: React.ReactNode;
}

/** Renders an API/query error with a French title, icon and optional retry. */
export function ErrorState({ error, onRetry, title, className, size = "md", variant = "card", action }: ErrorStateProps) {
  let icon: React.ReactNode = <ServerCrash />;
  let defaultTitle = "Impossible de charger ces données";
  if (isApiError(error)) {
    if (error.isForbidden) {
      icon = <Lock />;
      defaultTitle = "Accès refusé";
    } else if (error.isNotFound) {
      icon = <FileQuestion />;
      defaultTitle = "Élément introuvable";
    } else if (error.isNetwork) {
      icon = <CloudOff />;
      defaultTitle = "Service injoignable";
    }
  }
  const retryable = !isApiError(error) || !(error.isForbidden || error.isNotFound);
  return (
    <EmptyState
      icon={icon}
      title={title ?? defaultTitle}
      description={errorMessage(error)}
      size={size}
      variant={variant}
      className={className}
      action={
        (onRetry && retryable) || action ? (
          <>
            {onRetry && retryable ? (
              <Button variant="secondary" size="sm" onClick={onRetry} leftIcon={<RefreshCw aria-hidden />}>
                Réessayer
              </Button>
            ) : null}
            {action}
          </>
        ) : undefined
      }
    />
  );
}
