"use client";

import * as React from "react";
import { Database, FileText, ListChecks, ShieldAlert, Waypoints } from "lucide-react";

import { RequireRole, useHasRole } from "@/components/auth/require-role";
import { PageHeader } from "@/components/ui/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCurrentProject } from "@/hooks/use-current-project";
import { useSources } from "@/lib/api/hooks";
import { AddContentMenu } from "./add-content-menu";
import { DocumentsPanel } from "./documents-panel";
import { JobsPanel } from "./jobs-panel";
import { QuarantinePanel } from "./quarantine-panel";
import { SourcesPanel } from "./sources-panel";
import { useUrlParams } from "./use-url-params";

const TABS = ["documents", "sources", "jobs", "quarantine"] as const;
type SourcesTab = (typeof TABS)[number];

function isTab(value: string | null): value is SourcesTab {
  return value !== null && (TABS as readonly string[]).includes(value);
}

/** Sources screen: Documents | Sources | Traitements | Quarantaine (owners) — tab kept in `?tab=`. */
export function SourcesView() {
  const { slug } = useCurrentProject();
  const { get, set } = useUrlParams();
  const tabParam = get("tab");
  const tab: SourcesTab = isTab(tabParam) ? tabParam : "documents";
  const sources = useSources(slug);
  const isOwner = useHasRole("owner");

  return (
    <div className="grid grid-cols-1 gap-2">
      <PageHeader
        icon={<Database />}
        title="Sources"
        description="Sources métier connectées, documents ingérés et suivi chronométré du pipeline : extraction, données personnelles, classification, découpage, vectorisation, indexation."
        actions={
          <RequireRole min="editor">
            <AddContentMenu slug={slug} />
          </RequireRole>
        }
        className="pb-2"
      />
      <Tabs value={tab} onValueChange={(v) => set({ tab: v === "documents" ? null : v })}>
        <TabsList aria-label="Sections des sources">
          <TabsTrigger value="documents">
            <FileText aria-hidden />
            Documents
          </TabsTrigger>
          <TabsTrigger value="sources" count={sources.data?.length}>
            <Waypoints aria-hidden />
            Sources
          </TabsTrigger>
          <TabsTrigger value="jobs">
            <ListChecks aria-hidden />
            Traitements
          </TabsTrigger>
          {isOwner ? (
            <TabsTrigger value="quarantine">
              <ShieldAlert aria-hidden />
              Quarantaine
            </TabsTrigger>
          ) : null}
        </TabsList>
        <TabsContent value="documents">
          <DocumentsPanel slug={slug} sources={sources.data} sourcesLoading={sources.isPending} />
        </TabsContent>
        <TabsContent value="sources">
          <SourcesPanel
            slug={slug}
            sources={sources.data}
            isPending={sources.isPending}
            error={sources.isError ? sources.error : null}
            onRetry={() => void sources.refetch()}
            onShowDocuments={(sourceId) => set({ tab: null, source: sourceId, page: null, q: null, kind: null, status: null, classification: null })}
          />
        </TabsContent>
        <TabsContent value="jobs">
          <JobsPanel slug={slug} />
        </TabsContent>
        {isOwner ? (
          <TabsContent value="quarantine">
            <QuarantinePanel slug={slug} />
          </TabsContent>
        ) : null}
      </Tabs>
    </div>
  );
}
