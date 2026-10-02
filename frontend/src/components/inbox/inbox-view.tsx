"use client";

import { GitCompareArrows, Inbox, ListChecks, Lock } from "lucide-react";

import { useUrlParams } from "@/components/sources/use-url-params";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCurrentProject } from "@/hooks/use-current-project";
import { useInboxCount } from "@/lib/api/features-feed";
import { ConflictsPanel } from "./conflicts-panel";
import { ProposalsPanel } from "./proposals-panel";

type InboxTab = "proposals" | "conflicts";

/** « Revue mémoire » : proposals to validate and contradictions to arbitrate (docs/FEATURES.md F1). */
export function InboxView() {
  const { slug, project, canEdit } = useCurrentProject();
  const { get, set } = useUrlParams();
  const tab: InboxTab = get("tab") === "conflicts" ? "conflicts" : "proposals";
  const count = useInboxCount(slug, canEdit);

  return (
    <div className="flex min-w-0 flex-col">
      <PageHeader
        icon={<Inbox />}
        eyebrow={project.name}
        title="Revue mémoire"
        description="Validez, rejetez ou fusionnez les propositions extraites des sources, et arbitrez les contradictions détectées entre items."
        meta={
          count.data ? (
            <Badge tone={count.data.total ? "amber" : "green"} size="sm" dot>
              {count.data.total ? `${count.data.total} élément(s) à traiter` : "Tout est trié"}
            </Badge>
          ) : null
        }
      />
      {!canEdit ? (
        <EmptyState
          icon={<Lock />}
          title="Accès réservé aux éditeurs"
          description="Le tri de la mémoire est réservé aux éditeurs et propriétaires du projet."
        />
      ) : (
        <Tabs value={tab} onValueChange={(next) => set({ tab: next === "conflicts" ? "conflicts" : null })}>
          <TabsList aria-label="Sections du tri" className="mb-5">
            <TabsTrigger value="proposals" count={count.data?.proposals}>
              <ListChecks aria-hidden />
              Propositions
            </TabsTrigger>
            <TabsTrigger value="conflicts" count={count.data?.conflicts}>
              <GitCompareArrows aria-hidden />
              Contradictions
            </TabsTrigger>
          </TabsList>
          <TabsContent value="proposals">
            <ProposalsPanel slug={slug} active={tab === "proposals"} />
          </TabsContent>
          <TabsContent value="conflicts">
            <ConflictsPanel slug={slug} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
