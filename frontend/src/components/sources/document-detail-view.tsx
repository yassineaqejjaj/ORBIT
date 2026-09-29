"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Brain,
  Braces,
  Download,
  Eraser,
  ExternalLink,
  GitBranch,
  Layers,
  ListChecks,
  PencilLine,
  RefreshCw,
  Tag,
} from "lucide-react";
import { toast } from "sonner";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { ClassificationBanner } from "@/components/domain/classification-banner";
import { RelativeTime } from "@/components/domain/relative-time";
import { SourceKindIcon } from "@/components/domain/source-kind-icon";
import { projectHref } from "@/components/layout/nav";
import { useBreadcrumbLabel } from "@/components/layout/shell-context";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ErrorState } from "@/components/ui/error-state";
import { JsonViewer } from "@/components/ui/json-viewer";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCurrentProject } from "@/hooks/use-current-project";
import { errorMessage, isApiError } from "@/lib/api/client";
import {
  useDocument,
  useDownloadDocumentRaw,
  useForgetDocument,
  useMembers,
  useReprocessDocument,
} from "@/lib/api/hooks";
import type { DocumentDetail, Member } from "@/lib/api/types";
import { getMeta, SOURCE_KIND_META } from "@/lib/enums";
import { formatDate, formatDateTime, formatNumber, formatTokens, plural, shortId } from "@/lib/format";
import { AclChips } from "./acl-chips";
import { ChunkList } from "./chunk-list";
import { DerivedMemory } from "./derived-memory";
import { DocumentProcessing } from "./document-processing";
import { DocumentStatusBadge, isDocumentActive } from "./document-status";
import { DocumentVersions } from "./document-versions";
import { EditDocumentDialog } from "./edit-document-dialog";
import { JobStepsInline } from "./job-steps";
import { useUrlParams } from "./use-url-params";

const TABS = ["content", "processing", "versions", "memory", "metadata"] as const;
type DocumentTab = (typeof TABS)[number];

const MIME_EXTENSIONS: Record<string, string> = {
  "application/pdf": "pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
  "text/markdown": "md",
  "text/x-markdown": "md",
  "text/html": "html",
  "text/plain": "txt",
  "application/json": "json",
  "text/csv": "csv",
};

function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function downloadFilename(doc: Pick<DocumentDetail, "title" | "mime_type">): string {
  const ext = MIME_EXTENSIONS[doc.mime_type.split(";")[0]?.trim() ?? ""] ?? "";
  const base = doc.title.replace(/[\\/:*?"<>|]+/g, " ").trim() || "document";
  if (!ext || base.toLowerCase().endsWith(`.${ext}`)) return base;
  return `${base}.${ext}`;
}

function memberName(members: readonly Member[] | undefined, id: string | null): string | null {
  if (!id) return null;
  const m = members?.find((x) => x.user.id === id);
  return m ? m.user.full_name || m.user.email : `Utilisateur ${shortId(id)}`;
}

function DetailSkeleton() {
  return (
    <div className="grid gap-6" aria-busy="true" aria-label="Chargement du document">
      <Skeleton className="h-4 w-32" />
      <div className="flex items-start gap-3">
        <Skeleton className="size-10 rounded-lg" />
        <div className="grid flex-1 gap-2">
          <Skeleton className="h-3 w-40" />
          <Skeleton className="h-6 w-96 max-w-full" />
          <div className="flex gap-2">
            <Skeleton className="h-5 w-24" />
            <Skeleton className="h-5 w-20" />
            <Skeleton className="h-5 w-12" />
          </div>
        </div>
      </div>
      <Skeleton className="h-24 rounded-xl" />
      <Skeleton className="h-9 w-full max-w-xl" />
      <div className="grid gap-3">
        {Array.from({ length: 3 }, (_, i) => (
          <Card key={i} className="p-4">
            <SkeletonText lines={4} />
          </Card>
        ))}
      </div>
    </div>
  );
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid min-w-0 gap-0.5">
      <dt className="text-[11.5px] text-muted-foreground">{label}</dt>
      <dd className="truncate text-[13px] text-foreground">{children}</dd>
    </div>
  );
}

function Tombstone({ doc, members }: { doc: DocumentDetail; members: readonly Member[] | undefined }) {
  const by = memberName(members, doc.forgotten_by);
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center gap-4 px-6 py-12 text-center">
        <span className="flex size-12 items-center justify-center rounded-xl border border-border bg-muted text-muted-foreground">
          <Eraser className="size-6" aria-hidden />
        </span>
        <div className="grid max-w-lg gap-1.5">
          <h2 className="text-base font-semibold tracking-tight text-foreground">Document oublié</h2>
          <p className="text-[13px] leading-relaxed text-muted-foreground">
            Oublié le {formatDateTime(doc.forgotten_at)}
            {by ? ` par ${by}` : ""}. Son contenu a été effacé et retiré des index : il n&apos;est plus jamais servi aux
            agents. Seuls le titre et les métadonnées sont conservés pour la traçabilité (journal d&apos;audit).
          </p>
          {doc.status_reason ? (
            <p className="text-[13px] text-foreground">
              <span className="text-muted-foreground">Motif : </span>
              {doc.status_reason}
            </p>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

/** Document detail: header, governance banner, actions and Contenu / Traitement / Versions / Mémoire / Métadonnées. */
export function DocumentDetailView() {
  const params = useParams<{ documentId: string }>();
  const documentId = typeof params.documentId === "string" ? safeDecode(params.documentId) : "";
  const { slug, canEdit, isOwner } = useCurrentProject();
  const { get, set } = useUrlParams();
  const tabParam = get("tab");
  const tab: DocumentTab = tabParam !== null && (TABS as readonly string[]).includes(tabParam) ? (tabParam as DocumentTab) : "content";

  const document = useDocument(slug, documentId || undefined);
  const members = useMembers(slug);
  const reprocess = useReprocessDocument(slug, { meta: { silentError: true } });
  const forget = useForgetDocument(slug, { meta: { silentError: true } });
  const download = useDownloadDocumentRaw(slug, { meta: { silentError: true } });
  const [editOpen, setEditOpen] = React.useState(false);
  const [forgetOpen, setForgetOpen] = React.useState(false);

  useBreadcrumbLabel(documentId, document.data?.title);

  const sourcesHref = projectHref(slug, "sources");
  const backLink = (
    <Link
      href={sourcesHref}
      className="inline-flex w-fit items-center gap-1.5 rounded text-[13px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <ArrowLeft className="size-3.5" aria-hidden />
      Retour aux sources
    </Link>
  );

  if (document.isPending) return <DetailSkeleton />;
  if (document.isError) {
    const notFound = document.error.isNotFound;
    return (
      <div className="grid gap-6">
        {backLink}
        <ErrorState
          size="lg"
          error={document.error}
          title={notFound ? "Document introuvable" : undefined}
          onRetry={notFound ? undefined : () => void document.refetch()}
          action={
            notFound ? (
              <Button asChild size="sm">
                <Link href={sourcesHref}>Voir les documents</Link>
              </Button>
            ) : undefined
          }
        />
        {notFound ? (
          <p className="text-center text-xs text-muted-foreground">
            Ce document n&apos;existe pas ou vous n&apos;êtes pas autorisé à le consulter (droits d&apos;accès ou classification).
          </p>
        ) : null}
      </div>
    );
  }

  const doc = document.data;
  const forgotten = doc.status === "forgotten";
  const active = isDocumentActive(doc.status) || doc.jobs.some((j) => j.status === "queued" || j.status === "running");
  const latestJob = [...doc.jobs].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0];
  const totalTokens = doc.chunks.reduce((acc, c) => acc + c.token_count, 0);
  const kindMeta = getMeta(SOURCE_KIND_META, doc.source_kind);
  const uriIsLink = Boolean(doc.uri && /^https?:\/\//i.test(doc.uri));

  const runReprocess = async () => {
    try {
      await reprocess.mutateAsync(doc.id);
      toast.success("Retraitement lancé", {
        description: "Extraction, détection des données personnelles, classification et indexation vont être rejouées.",
      });
      set({ tab: "processing" });
    } catch (error) {
      toast.error("Impossible de relancer le traitement", { description: errorMessage(error) });
    }
  };

  const runDownload = async () => {
    try {
      await download.mutateAsync({ id: doc.id, filename: downloadFilename(doc) });
    } catch (error) {
      if (isApiError(error) && error.isNotFound) {
        toast.error("Aucun fichier original", {
          description: "Ce contenu a été saisi ou importé : il n'existe pas de fichier source téléchargeable.",
        });
      } else {
        toast.error("Téléchargement impossible", { description: errorMessage(error) });
      }
    }
  };

  const runForget = async (reason: string) => {
    try {
      await forget.mutateAsync({ id: doc.id, reason });
      toast.success("Document oublié", {
        description: "Retiré des index, contenu effacé, oubli propagé à la mémoire dérivée et aux snapshots.",
      });
      setForgetOpen(false);
    } catch (error) {
      toast.error("L'oubli a échoué", { description: errorMessage(error) });
    }
  };

  return (
    <div className="grid grid-cols-1 gap-5">
      {backLink}

      <header className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <SourceKindIcon kind={doc.source_kind} chip className="mt-0.5 [&>span]:size-10 [&_svg]:size-5" />
          <div className="grid min-w-0 gap-1.5">
            <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              <Link
                href={`${sourcesHref}?source=${encodeURIComponent(doc.source_id)}`}
                className="rounded font-medium hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {doc.source_name || "Source"}
              </Link>
              <span aria-hidden>·</span>
              <span>{kindMeta.label}</span>
              {doc.external_id ? (
                <>
                  <span aria-hidden>·</span>
                  <span className="font-mono">{doc.external_id}</span>
                </>
              ) : null}
            </p>
            <h1 className="text-xl font-semibold tracking-tight text-foreground text-balance sm:text-[22px]">
              {forgotten ? <span className="text-muted-foreground line-through decoration-1">{doc.title}</span> : doc.title}
            </h1>
            <div className="flex flex-wrap items-center gap-1.5">
              <ClassificationBadge level={doc.classification} size="md" />
              <DocumentStatusBadge status={doc.status} reason={doc.status_reason} size="md" />
              <Badge size="md" variant="outline" tone={doc.current_version > 1 ? "violet" : "neutral"} icon={<GitBranch aria-hidden />}>
                Version {doc.current_version}
              </Badge>
              {doc.pii_count > 0 ? (
                <Badge size="md" tone="pink">
                  {plural(doc.pii_count, "donnée personnelle", "données personnelles")}
                </Badge>
              ) : null}
            </div>
          </div>
        </div>
        {!forgotten && canEdit ? (
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              leftIcon={<RefreshCw aria-hidden />}
              onClick={runReprocess}
              loading={reprocess.isPending}
              disabled={active}
              title={active ? "Un traitement est déjà en cours" : undefined}
            >
              Retraiter
            </Button>
            <Button variant="secondary" size="sm" leftIcon={<PencilLine aria-hidden />} onClick={() => setEditOpen(true)}>
              Modifier
            </Button>
            <Button
              variant="secondary"
              size="sm"
              leftIcon={<Download aria-hidden />}
              onClick={runDownload}
              loading={download.isPending}
            >
              Télécharger l&apos;original
            </Button>
            {isOwner ? (
              <Button variant="destructive-outline" size="sm" leftIcon={<Eraser aria-hidden />} onClick={() => setForgetOpen(true)}>
                Oublier
              </Button>
            ) : null}
          </div>
        ) : null}
      </header>

      {!forgotten ? <ClassificationBanner level={doc.classification} context="display" /> : null}

      {!forgotten && active && latestJob ? (
        <Alert
          tone="blue"
          icon={<RefreshCw className="animate-spin" aria-hidden />}
          title="Traitement en cours"
          action={<JobStepsInline job={latestJob} className="hidden sm:inline-flex" />}
        >
          La page s&apos;actualise automatiquement à chaque étape du pipeline.
        </Alert>
      ) : null}
      {doc.status === "failed" ? (
        <Alert
          tone="red"
          title="Le traitement de ce document a échoué"
          action={
            canEdit ? (
              <Button size="xs" variant="secondary" onClick={runReprocess} loading={reprocess.isPending} leftIcon={<RefreshCw aria-hidden />}>
                Relancer
              </Button>
            ) : undefined
          }
        >
          {doc.status_reason ?? "Consultez l'onglet Traitement pour le détail de l'étape en échec."}
        </Alert>
      ) : null}

      <Card>
        <CardContent className="grid gap-4 p-4 sm:p-5">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4 xl:grid-cols-8">
            <Meta label="Auteur">{doc.author || "—"}</Meta>
            <Meta label="Date métier">{formatDate(doc.source_updated_at)}</Meta>
            <Meta label="Ingéré le">{formatDate(doc.created_at)}</Meta>
            <Meta label="Mis à jour">
              <RelativeTime date={doc.updated_at} />
            </Meta>
            <Meta label="Extraits">{formatNumber(doc.chunk_count || doc.chunks.length, 0)}</Meta>
            <Meta label="Tokens">{formatTokens(totalTokens)}</Meta>
            <Meta label="Format">
              <span className="font-mono text-xs">{doc.mime_type || "—"}</span>
            </Meta>
            <Meta label="Lien">
              {doc.uri ? (
                uriIsLink ? (
                  <a
                    href={doc.uri}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-primary hover:underline"
                  >
                    Ouvrir <ExternalLink className="size-3" aria-hidden />
                  </a>
                ) : (
                  <span className="font-mono text-xs" title={doc.uri}>
                    {doc.uri}
                  </span>
                )
              ) : (
                "—"
              )}
            </Meta>
          </dl>
          <div className="flex flex-col gap-3 border-t border-border pt-3 sm:flex-row sm:items-center sm:gap-6">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="text-[11.5px] text-muted-foreground">Accès</span>
              <AclChips principals={doc.acl_principals} members={members.data} />
            </div>
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="text-[11.5px] text-muted-foreground">Étiquettes</span>
              {doc.tags.length > 0 ? (
                doc.tags.map((t) => (
                  <Badge key={t} variant="outline" icon={<Tag aria-hidden />}>
                    {t}
                  </Badge>
                ))
              ) : (
                <span className="text-xs text-subtle-foreground">Aucune</span>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <Tabs value={tab} onValueChange={(v) => set({ tab: v === "content" ? null : v })}>
        <TabsList aria-label="Sections du document">
          <TabsTrigger value="content" count={forgotten ? undefined : doc.chunks.length}>
            <Layers aria-hidden />
            Contenu
          </TabsTrigger>
          <TabsTrigger value="processing" count={doc.jobs.length}>
            <ListChecks aria-hidden />
            Traitement
          </TabsTrigger>
          <TabsTrigger value="versions" count={doc.versions.length}>
            <GitBranch aria-hidden />
            Versions
          </TabsTrigger>
          <TabsTrigger value="memory" count={doc.memory_items.length}>
            <Brain aria-hidden />
            Mémoire dérivée
          </TabsTrigger>
          <TabsTrigger value="metadata">
            <Braces aria-hidden />
            Métadonnées
          </TabsTrigger>
        </TabsList>
        <TabsContent value="content">
          {forgotten ? (
            <Tombstone doc={doc} members={members.data} />
          ) : (
            <ChunkList chunks={doc.chunks} version={doc.current_version} canSeeOriginal={canEdit} />
          )}
        </TabsContent>
        <TabsContent value="processing">
          <DocumentProcessing jobs={doc.jobs} />
        </TabsContent>
        <TabsContent value="versions">
          <DocumentVersions versions={doc.versions} currentVersion={doc.current_version} />
        </TabsContent>
        <TabsContent value="memory">
          <DerivedMemory slug={slug} items={doc.memory_items} />
        </TabsContent>
        <TabsContent value="metadata">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
            <Card>
              <CardHeader>
                <CardTitle>Informations techniques</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="grid gap-3 text-[13px]">
                  {(
                    [
                      ["Identifiant", doc.id],
                      ["Source", doc.source_id],
                      ["Identifiant externe", doc.external_id ?? "—"],
                      ["URI", doc.uri ?? "—"],
                      ["Type MIME", doc.mime_type || "—"],
                      ["Créé", formatDateTime(doc.created_at)],
                      ["Mis à jour", formatDateTime(doc.updated_at)],
                      ...(forgotten
                        ? ([
                            ["Oublié le", formatDateTime(doc.forgotten_at)],
                            ["Oublié par", memberName(members.data, doc.forgotten_by) ?? "—"],
                          ] as Array<[string, string]>)
                        : []),
                    ] as Array<[string, string]>
                  ).map(([label, value]) => (
                    <div key={label} className="grid gap-0.5">
                      <dt className="text-xs text-muted-foreground">{label}</dt>
                      <dd className="break-all font-mono text-[12px] text-foreground">{value}</dd>
                    </div>
                  ))}
                </dl>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Métadonnées extraites</CardTitle>
              </CardHeader>
              <CardContent>
                {Object.keys(doc.metadata ?? {}).length > 0 ? (
                  <JsonViewer data={doc.metadata} defaultExpandDepth={2} />
                ) : (
                  <p className="text-[13px] text-muted-foreground">Aucune métadonnée complémentaire pour ce document.</p>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>

      {!forgotten && canEdit ? <EditDocumentDialog slug={slug} document={doc} open={editOpen} onOpenChange={setEditOpen} /> : null}
      {isOwner && !forgotten ? (
        <ConfirmDialog
          open={forgetOpen}
          onOpenChange={setForgetOpen}
          title="Oublier ce document ?"
          description={`« ${doc.title} » sera définitivement retiré de la plateforme.`}
          destructive
          reason="required"
          reasonLabel="Justification (journalisée)"
          reasonPlaceholder="Ex. information erronée, demande d'effacement RGPD, document diffusé par erreur…"
          confirmLabel="Oublier définitivement"
          onConfirm={runForget}
          loading={forget.isPending}
        >
          <div className="grid gap-2 rounded-lg border border-red-200 bg-red-50 px-3.5 py-3 text-[13px] text-red-950 dark:border-red-400/30 dark:bg-red-400/10 dark:text-red-100">
            <p className="font-medium">Conséquences de l&apos;oubli sélectif :</p>
            <ul className="grid list-disc gap-1 pl-4 text-[12.5px] leading-relaxed">
              <li>suppression des {plural(doc.chunks.length, "extrait")} des index de recherche ;</li>
              <li>contenu remplacé par « [oublié] » en base (titre et métadonnées conservés pour l&apos;audit) ;</li>
              <li>
                {doc.memory_items.length > 0
                  ? `${plural(doc.memory_items.length, "élément", "éléments")} de mémoire dérivée oublié${doc.memory_items.length > 1 ? "s" : ""} ou affaibli${doc.memory_items.length > 1 ? "s" : ""} ;`
                  : "propagation à la mémoire dérivée éventuelle ;"}
              </li>
              <li>snapshots de contexte marqués (éléments caviardés à l&apos;affichage) ;</li>
              <li>action irréversible, tracée dans le journal d&apos;audit.</li>
            </ul>
          </div>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
