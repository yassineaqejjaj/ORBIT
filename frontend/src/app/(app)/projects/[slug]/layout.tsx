"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { CurrentProjectProvider } from "@/hooks/use-current-project";
import { useProject } from "@/lib/api/hooks";

const LAST_PROJECT_KEY = "orbit:last-project";

function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function ProjectSkeleton() {
  return (
    <div className="grid gap-6" aria-busy="true" aria-label="Chargement du projet">
      <div className="flex items-start gap-3">
        <Skeleton className="size-9 rounded-lg" />
        <div className="grid flex-1 gap-2">
          <Skeleton className="h-6 w-64" />
          <Skeleton className="h-4 w-96 max-w-full" />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-28 rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-72 rounded-xl" />
    </div>
  );
}

/** Resolves the project from the URL and provides it (with the caller role) to every project page. */
export default function ProjectLayout({ children }: { children: React.ReactNode }) {
  const params = useParams<{ slug: string }>();
  const slug = typeof params.slug === "string" ? safeDecode(params.slug) : "";
  const project = useProject(slug);

  React.useEffect(() => {
    if (!project.data) return;
    try {
      window.localStorage.setItem(LAST_PROJECT_KEY, project.data.slug);
    } catch {
      // storage unavailable
    }
  }, [project.data]);

  if (project.isPending) return <ProjectSkeleton />;
  if (project.isError) {
    const notFound = project.error.isNotFound;
    const forbidden = project.error.isForbidden;
    return (
      <ErrorState
        size="lg"
        error={project.error}
        title={notFound ? "Projet introuvable" : forbidden ? "Accès au projet refusé" : undefined}
        onRetry={notFound || forbidden ? undefined : () => void project.refetch()}
        className="mt-6"
        action={
          <Button asChild size="sm" variant={notFound || forbidden ? "primary" : "ghost"}>
            <Link href="/projects">
              <ArrowLeft aria-hidden />
              Retour aux projets
            </Link>
          </Button>
        }
      />
    );
  }

  return (
    <CurrentProjectProvider project={project.data}>
      {children}
    </CurrentProjectProvider>
  );
}
