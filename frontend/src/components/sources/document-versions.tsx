"use client";

import * as React from "react";
import { GitBranch, History } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { CopyButton } from "@/components/ui/code-block";
import { EmptyState } from "@/components/ui/empty-state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { DocumentVersion } from "@/lib/api/types";
import { formatBytes, formatDateTime, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

/** "Versions" tab: every ingested version, the current one highlighted, with the superseded-chunks explanation. */
export function DocumentVersions({ versions, currentVersion }: { versions: readonly DocumentVersion[]; currentVersion: number }) {
  const sorted = React.useMemo(() => [...versions].sort((a, b) => b.version - a.version), [versions]);
  if (sorted.length === 0) {
    return (
      <EmptyState
        icon={<History />}
        title="Aucune version enregistrée"
        description="La première version apparaîtra à la fin de l'extraction."
      />
    );
  }
  return (
    <div className="grid gap-4">
      {sorted.length > 1 ? (
        <Alert tone="blue" icon={<GitBranch aria-hidden />} title={`${sorted.length} versions ingérées`}>
          À chaque nouvelle version (même identifiant externe ou ré-upload du même titre), les extraits des versions
          précédentes passent au statut <strong>Remplacé</strong>. Ils restent indexés pour que la gouvernance puisse
          expliquer leur exclusion (<span className="font-mono text-[12px]">EXCLUDED_SUPERSEDED</span>) mais ne sont plus
          jamais servis aux agents : seul le contenu de la version {currentVersion} alimente les contextes.
        </Alert>
      ) : (
        <p className="text-xs text-muted-foreground">
          Une seule version pour l&apos;instant. Un ré-upload du même titre dans la même source créera la version 2 et remplacera
          les extraits actuels.
        </p>
      )}
      <Card className="overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Version</TableHead>
              <TableHead>Ingérée le</TableHead>
              <TableHead className="text-right">Taille</TableHead>
              <TableHead className="text-right">Caractères</TableHead>
              <TableHead>Empreinte (SHA-256)</TableHead>
              <TableHead>Extraits</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((v) => {
              const current = v.version === currentVersion;
              return (
                <TableRow key={v.id} selected={current}>
                  <TableCell>
                    <span className="flex items-center gap-2">
                      <span className={cn("font-semibold tabular-nums", current ? "text-foreground" : "text-muted-foreground")}>
                        v{v.version}
                      </span>
                      {current ? (
                        <Badge tone="teal" dot>
                          Courante
                        </Badge>
                      ) : null}
                    </span>
                  </TableCell>
                  <TableCell className="whitespace-nowrap">{formatDateTime(v.created_at)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatBytes(v.size_bytes)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatNumber(v.char_count, 0)}</TableCell>
                  <TableCell>
                    <span className="inline-flex items-center gap-1">
                      <span className="font-mono text-xs text-muted-foreground" title={v.content_hash}>
                        {v.content_hash.slice(0, 12)}…
                      </span>
                      <CopyButton value={v.content_hash} label="Copier l'empreinte" />
                    </span>
                  </TableCell>
                  <TableCell>
                    {current ? (
                      <Badge tone="green" size="sm">
                        Actifs — servis aux agents
                      </Badge>
                    ) : (
                      <Badge tone="amber" size="sm">
                        Remplacés — exclus
                      </Badge>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
