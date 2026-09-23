"use client";

import "./globals.css";

/** Last-resort boundary (replaces the root layout). */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="fr">
      <body className="flex min-h-dvh items-center justify-center bg-background px-4 font-sans text-foreground">
        <div className="grid max-w-md justify-items-center gap-4 text-center">
          <h1 className="text-xl font-semibold">ORBIT est momentanément indisponible</h1>
          <p className="text-sm text-muted-foreground">
            Une erreur critique empêche l&apos;affichage de l&apos;application. Rechargez la page pour réessayer.
          </p>
          {error.digest ? <code className="font-mono text-xs text-muted-foreground">Réf. {error.digest}</code> : null}
          <button
            type="button"
            onClick={reset}
            className="h-9 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary-hover"
          >
            Recharger
          </button>
        </div>
      </body>
    </html>
  );
}
