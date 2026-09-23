"use client";

import * as React from "react";
import { Brain, Database, FolderKanban, FolderPlus, Plus, Search, Telescope } from "lucide-react";

import { useShell } from "@/components/layout/shell-context";
import { ProjectCard, ProjectCardSkeleton } from "@/components/projects/project-card";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { StatCard } from "@/components/ui/stat-card";
import { useMe, useProjects } from "@/lib/api/hooks";
import type { ProjectSummary } from "@/lib/api/types";
import { formatNumber } from "@/lib/format";
import { normalizeText } from "@/lib/utils";

type SortKey = "recent" | "name" | "activity";

const SORTS: Record<SortKey, (a: ProjectSummary, b: ProjectSummary) => number> = {
  recent: (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  name: (a, b) => a.name.localeCompare(b.name, "fr", { sensitivity: "base" }),
  activity: (a, b) => b.stats.context_requests_7d - a.stats.context_requests_7d,
};

export function ProjectsView() {
  const { openCreateProject } = useShell();
  const { data: me } = useMe();
  const projects = useProjects();
  const [query, setQuery] = React.useState("");
  const [sort, setSort] = React.useState<SortKey>("recent");

  const list = React.useMemo(() => {
    const items = projects.data ?? [];
    const q = normalizeText(query);
    const filtered = q
      ? items.filter((p) => normalizeText(`${p.name} ${p.slug} ${p.description ?? ""}`).includes(q))
      : items;
    return [...filtered].sort(SORTS[sort]);
  }, [projects.data, query, sort]);

  const totals = React.useMemo(() => {
    const items = projects.data ?? [];
    return items.reduce(
      (acc, p) => ({
        sources: acc.sources + p.stats.sources,
        documents: acc.documents + p.stats.documents,
        memory: acc.memory + p.stats.memory_items,
        requests: acc.requests + p.stats.context_requests_7d,
      }),
      { sources: 0, documents: 0, memory: 0, requests: 0 },
    );
  }, [projects.data]);

  const hasProjects = (projects.data?.length ?? 0) > 0;
  const firstName = me?.full_name?.split(" ")[0];

  return (
    <div className="grid grid-cols-1 gap-6">
      <PageHeader
        eyebrow={firstName ? `Bonjour ${firstName}` : undefined}
        title="Projets"
        description={
          me?.is_admin
            ? "Tous les projets de la plateforme (vue administrateur). Chaque projet regroupe ses sources, sa mémoire, ses agents et ses contextes."
            : "Vos projets ORBIT. Chaque projet regroupe ses sources, sa mémoire, ses agents et ses contextes servis."
        }
        actions={
          <Button onClick={openCreateProject} leftIcon={<Plus aria-hidden />}>
            Nouveau projet
          </Button>
        }
      />

      {projects.isError ? (
        <ErrorState error={projects.error} onRetry={() => void projects.refetch()} />
      ) : (
        <>
          <section aria-label="Synthèse" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard
              label="Projets"
              value={formatNumber(projects.data?.length ?? 0, 0)}
              icon={<FolderKanban />}
              tone="teal"
              loading={projects.isPending}
            />
            <StatCard
              label="Sources connectées"
              value={formatNumber(totals.sources, 0)}
              hint={`${formatNumber(totals.documents, 0)} documents`}
              icon={<Database />}
              tone="blue"
              loading={projects.isPending}
            />
            <StatCard
              label="Éléments de mémoire"
              value={formatNumber(totals.memory, 0)}
              icon={<Brain />}
              tone="violet"
              loading={projects.isPending}
            />
            <StatCard
              label="Contextes servis (7 j)"
              value={formatNumber(totals.requests, 0)}
              icon={<Telescope />}
              tone="orange"
              loading={projects.isPending}
            />
          </section>

          {projects.isPending || hasProjects ? (
            <section aria-label="Liste des projets" className="grid grid-cols-1 gap-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Filtrer par nom, identifiant ou description…"
                  leftIcon={<Search aria-hidden />}
                  className="sm:max-w-sm"
                  aria-label="Filtrer les projets"
                  disabled={projects.isPending}
                />
                <SegmentedControl<SortKey>
                  value={sort}
                  onValueChange={setSort}
                  className="self-start sm:self-auto"
                  aria-label="Trier les projets"
                  options={[
                    { value: "recent", label: "Récents" },
                    { value: "activity", label: "Activité" },
                    { value: "name", label: "Nom" },
                  ]}
                />
              </div>

              {projects.isPending ? (
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                  {Array.from({ length: 3 }, (_, i) => (
                    <ProjectCardSkeleton key={i} />
                  ))}
                </div>
              ) : list.length === 0 ? (
                <EmptyState
                  icon={<Search />}
                  title="Aucun projet ne correspond"
                  description={`Aucun projet ne contient « ${query.trim()} ».`}
                  action={
                    <Button variant="secondary" size="sm" onClick={() => setQuery("")}>
                      Effacer le filtre
                    </Button>
                  }
                />
              ) : (
                <ul className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                  {list.map((p) => (
                    <li key={p.id}>
                      <ProjectCard project={p} />
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ) : (
            <EmptyState
              size="lg"
              icon={<FolderPlus />}
              title="Créez votre premier projet"
              description="Un projet ORBIT réunit vos sources métier (documents, tickets, CRM, retours), une mémoire gouvernée et les agents IA qui l'exploitent."
              action={
                <Button onClick={openCreateProject} leftIcon={<Plus aria-hidden />}>
                  Nouveau projet
                </Button>
              }
            />
          )}
        </>
      )}
    </div>
  );
}
