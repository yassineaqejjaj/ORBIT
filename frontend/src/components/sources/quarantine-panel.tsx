"use client";

import * as React from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { projectHref } from "@/components/layout/nav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import * as api from "@/lib/api/endpoints";
import { errorMessage, type ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type { QuarantinedChunk } from "@/lib/api/types";

const quarantineKey = (slug: string) => [...queryKeys.project.documents.all(slug), "quarantine"] as const;

/** Owners: chunks held in quarantine (suspected prompt injection, AI security §A1) — review and release. */
export function QuarantinePanel({ slug }: { slug: string }) {
  const qc = useQueryClient();
  const query = useQuery<QuarantinedChunk[], ApiError>({
    queryKey: quarantineKey(slug),
    queryFn: ({ signal }) => api.listQuarantine(slug, { signal }),
  });
  const [pending, setPending] = React.useState<QuarantinedChunk | null>(null);
  const release = useMutation({
    mutationFn: (chunk: QuarantinedChunk) => api.releaseQuarantine(slug, chunk.document_id, chunk.id),
    onSuccess: () => {
      toast.success("Fragment libéré", { description: "Il pourra de nouveau être servi. Libération journalisée dans l'audit." });
      void qc.invalidateQueries({ queryKey: queryKeys.project.documents.all(slug) });
      void qc.invalidateQueries({ queryKey: queryKeys.project.overview(slug) });
    },
    onError: (error) => toast.error("Libération impossible", { description: errorMessage(error) }),
  });

  if (query.isPending) return <Skeleton className="h-32 w-full" />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (query.data.length === 0) {
    return (
      <EmptyState
        icon={<ShieldCheck />}
        title="Aucun fragment en quarantaine"
        description="Les extraits suspectés d'injection de prompt sont mis à l'écart à l'ingestion et apparaissent ici."
      />
    );
  }
  return (
    <div className="grid gap-3">
      <p className="text-[13px] text-muted-foreground">
        Ces extraits ne sont jamais servis aux agents (code <code>EXCLUDED_QUARANTINE</code>). Libérez-les seulement après vérification.
      </p>
      {query.data.map((chunk) => (
        <Card key={chunk.id}>
          <CardContent className="grid gap-2 pt-4">
            <div className="flex flex-wrap items-center gap-2">
              <ShieldAlert className="size-4 text-red-600 dark:text-red-400" aria-hidden />
              <Link
                href={`${projectHref(slug, "sources")}/${chunk.document_id}`}
                className="text-[13px] font-medium text-foreground hover:underline"
              >
                {chunk.document_title}
              </Link>
              <span className="text-xs text-muted-foreground">
                fragment n°{chunk.ordinal + 1} · v{chunk.version}
                {chunk.section ? ` · ${chunk.section}` : ""}
              </span>
              <Badge tone="danger" mono>
                score {chunk.injection_score.toFixed(2).replace(".", ",")}
              </Badge>
              <Button size="sm" variant="outline" className="ml-auto" onClick={() => setPending(chunk)}>
                Libérer
              </Button>
            </div>
            <ul className="flex flex-wrap gap-1.5" aria-label="Signaux détectés">
              {chunk.injection_reasons.map((reason) => (
                <li key={reason.code}>
                  <Badge tone="warning" title={reason.excerpt || undefined}>
                    {reason.label}
                  </Badge>
                </li>
              ))}
            </ul>
            <p className="line-clamp-3 whitespace-pre-wrap rounded-md bg-muted/50 p-2 font-mono text-xs text-muted-foreground">
              {chunk.text}
            </p>
          </CardContent>
        </Card>
      ))}
      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        title="Libérer ce fragment ?"
        description="Il sera de nouveau servi aux agents et pourra alimenter la mémoire. Action journalisée."
        confirmLabel="Libérer"
        onConfirm={async () => {
          if (pending) await release.mutateAsync(pending);
          setPending(null);
        }}
      />
    </div>
  );
}
