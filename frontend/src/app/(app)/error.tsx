"use client";

import * as React from "react";
import Link from "next/link";
import { RotateCcw, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";

/** Error boundary inside the app shell (sidebar/header stay usable). */
export default function AppError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  React.useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <EmptyState
      size="lg"
      icon={<TriangleAlert />}
      title="Cette vue a rencontré une erreur"
      description={
        <>
          Un problème inattendu est survenu lors de l&apos;affichage.
          {error.digest ? <span className="mt-1 block font-mono text-xs">Réf. {error.digest}</span> : null}
        </>
      }
      action={
        <>
          <Button onClick={reset} leftIcon={<RotateCcw aria-hidden />}>
            Réessayer
          </Button>
          <Button asChild variant="secondary">
            <Link href="/projects">Retour aux projets</Link>
          </Button>
        </>
      }
    />
  );
}
