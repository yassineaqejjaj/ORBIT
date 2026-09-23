"use client";

import * as React from "react";
import Link from "next/link";
import { RotateCcw, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";

export default function RootError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  React.useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-4">
      <div className="grid max-w-md justify-items-center gap-4 text-center">
        <span className="flex size-12 items-center justify-center rounded-xl border border-border bg-card text-destructive shadow-xs">
          <TriangleAlert className="size-5" aria-hidden />
        </span>
        <h1 className="text-xl font-semibold tracking-tight">Une erreur inattendue est survenue</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          L&apos;interface a rencontré un problème. Vous pouvez réessayer ; si le problème persiste, contactez
          l&apos;équipe plateforme en indiquant la référence ci-dessous.
        </p>
        {error.digest ? (
          <code className="rounded-md bg-muted px-2 py-1 font-mono text-xs text-muted-foreground">Réf. {error.digest}</code>
        ) : null}
        <div className="flex gap-2">
          <Button onClick={reset} leftIcon={<RotateCcw aria-hidden />}>
            Réessayer
          </Button>
          <Button asChild variant="secondary">
            <Link href="/projects">Retour aux projets</Link>
          </Button>
        </div>
      </div>
    </main>
  );
}
