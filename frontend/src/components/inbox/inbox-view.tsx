"use client";

import { CalendarClock, GitCompareArrows, Inbox, ListChecks, Lock, Tags } from "lucide-react";
import { toast } from "sonner";

import { useUrlParams } from "@/components/sources/use-url-params";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCurrentProject } from "@/hooks/use-current-project";
import { useInboxCount } from "@/lib/api/features-feed";
import { useReflectMemory } from "@/lib/api/hooks";
import { ConflictsPanel } from "./conflicts-panel";
import { EntitiesPanel } from "./entities-panel";
import { ProposalsPanel } from "./proposals-panel";

type InboxTab = "proposals" | "conflicts" | "entities";

/** « Revue mémoire » : proposals to validate and contradictions to arbitrate (docs/FEATURES.md F1). */
export function InboxView() {
  const { slug, project, canEdit } = useCurrentProject();
  const { get, set } = useUrlParams();
  const raw = get("tab");
  const tab: InboxTab = raw === "conflicts" || raw === "entities" ? raw : "proposals";
  const count = useInboxCount(slug, canEdit);
  const reflect = useReflectMemory(slug);

  return (
    <div className="flex min-w-0 flex-col">
      <PageHeader
        icon={<Inbox />}
        eyebrow={project.name}
        title="Revue mémoire"
        description="Validez, rejetez ou fusionnez les propositions extraites des sources, arbitrez les contradictions détectées entre items et fusionnez les entités qui désignent la même chose."
        actions={
          canEdit ? (
            <Button
              size="sm"
              variant="outline"
              disabled={reflect.isPending}
              onClick={() =>
                reflect.mutate(undefined, {
                  onSuccess: () =>
                    toast.success("Réflexion lancée : la synthèse « ce qui a changé » du mois dernier sera proposée ici."),
                  onError: (error) => toast.error(error.message),
                })
              }
            >
              <CalendarClock aria-hidden />
              Synthèse du mois dernier
            </Button>
          ) : null
        }
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
        <Tabs value={tab} onValueChange={(next) => set({ tab: next === "conflicts" || next === "entities" ? next : null })}>
          <TabsList aria-label="Sections du tri" className="mb-5">
            <TabsTrigger value="proposals" count={count.data?.proposals}>
              <ListChecks aria-hidden />
              Propositions
            </TabsTrigger>
            <TabsTrigger value="conflicts" count={count.data?.conflicts}>
              <GitCompareArrows aria-hidden />
              Contradictions
            </TabsTrigger>
            <TabsTrigger value="entities">
              <Tags aria-hidden />
              Entités
            </TabsTrigger>
          </TabsList>
          <TabsContent value="proposals">
            <ProposalsPanel slug={slug} active={tab === "proposals"} />
          </TabsContent>
          <TabsContent value="conflicts">
            <ConflictsPanel slug={slug} />
          </TabsContent>
          <TabsContent value="entities">{tab === "entities" ? <EntitiesPanel slug={slug} /> : null}</TabsContent>
        </Tabs>
      )}
    </div>
  );
}
