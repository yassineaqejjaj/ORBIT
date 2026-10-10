"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Brain, Database, FolderKanban, Plus, Rocket, Telescope } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { OrbitLogo } from "@/components/brand/orbit-logo";
import { projectHref } from "@/components/layout/nav";
import { useShell } from "@/components/layout/shell-context";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/kbd";
import { useCompleteOnboarding, useMe, useProjects } from "@/lib/api/hooks";
import { CLASSIFICATION_META, CLASSIFICATIONS, isSensitiveClassification, toClassification } from "@/lib/enums";
import { cn } from "@/lib/utils";

const STEP_COUNT = 4;
const MAX_LISTED_PROJECTS = 3;

/** First-login welcome tour. Open while the signed-in user has not finished or skipped it. */
export function OnboardingDialog() {
  const { data: me } = useMe();
  const complete = useCompleteOnboarding();
  const [step, setStep] = React.useState(0);

  const open = Boolean(me) && me?.onboarding_completed_at === null;

  // A restarted tour (user menu → « Revoir la visite ») always begins on the first step.
  React.useEffect(() => {
    if (open) setStep(0);
  }, [open]);

  if (!me) return null;

  const finish = () => {
    if (!complete.isPending) complete.mutate();
  };
  const isLast = step === STEP_COUNT - 1;

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? undefined : finish())}>
      <DialogContent size="lg" className="gap-5" aria-describedby="onboarding-description">
        <div className="flex items-center justify-between gap-3 pr-8">
          <OrbitLogo />
          <p className="text-xs font-medium text-muted-foreground" aria-live="polite">
            Étape {step + 1} sur {STEP_COUNT}
          </p>
        </div>

        <div className="flex gap-1.5" aria-hidden>
          {Array.from({ length: STEP_COUNT }, (_, i) => (
            <span
              key={i}
              className={cn(
                "h-1 flex-1 rounded-full transition-colors duration-200 motion-reduce:transition-none",
                i <= step ? "bg-primary" : "bg-surface-3",
              )}
            />
          ))}
        </div>

        <div className="min-h-[22rem]" id="onboarding-description">
          {step === 0 ? <WelcomeStep firstName={me.full_name.split(" ")[0] ?? me.full_name} /> : null}
          {step === 1 ? <ConceptsStep /> : null}
          {step === 2 ? <AccessStep clearance={me.clearance} isAdmin={me.is_admin} /> : null}
          {step === 3 ? <StartStep onDone={finish} /> : null}
        </div>

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
          {isLast ? (
            <span />
          ) : (
            <Button variant="ghost" onClick={finish} loading={complete.isPending}>
              Passer la visite
            </Button>
          )}
          <div className="flex gap-2 sm:justify-end">
            {step > 0 ? (
              <Button variant="secondary" onClick={() => setStep(step - 1)} leftIcon={<ArrowLeft aria-hidden />}>
                Précédent
              </Button>
            ) : null}
            {isLast ? (
              <Button onClick={finish} loading={complete.isPending}>
                Terminer
              </Button>
            ) : (
              <Button onClick={() => setStep(step + 1)} rightIcon={<ArrowRight aria-hidden />}>
                Suivant
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function StepHeader({ title, description }: { title: string; description: React.ReactNode }) {
  return (
    <DialogHeader className="gap-2">
      <DialogTitle className="text-xl">{title}</DialogTitle>
      <DialogDescription className="text-[15px] leading-relaxed">{description}</DialogDescription>
    </DialogHeader>
  );
}

function WelcomeStep({ firstName }: { firstName: string }) {
  return (
    <div className="grid gap-5">
      <StepHeader
        title={`Bienvenue sur ORBIT, ${firstName}`}
        description="ORBIT donne à vos agents IA le bon contexte, au bon moment — et la preuve de pourquoi. Cette visite de moins d’une minute présente l’essentiel."
      />
      <ul className="grid gap-3 text-sm">
        {[
          "Vos sources (documents, tickets, CRM, retours) sont ingérées, avec les données personnelles caviardées.",
          "ORBIT en tire une mémoire vivante : décisions, besoins, contraintes, avec leur provenance.",
          "Chaque agent reçoit un contexte gouverné : habilitations respectées, éléments retenus ou exclus expliqués.",
        ].map((text) => (
          <li key={text} className="flex gap-3 rounded-lg border border-border bg-surface-2/50 px-3.5 py-3">
            <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary" aria-hidden />
            <span className="leading-relaxed text-muted-foreground">{text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const CONCEPTS = [
  {
    icon: Database,
    title: "Sources",
    text: "Les contenus de votre équipe : fichiers, SharePoint, Confluence, Jira, MCP…",
  },
  {
    icon: Brain,
    title: "Mémoire",
    text: "Les décisions et connaissances extraites, à valider dans la Revue mémoire.",
  },
  {
    icon: Telescope,
    title: "Contexte",
    text: "Ce que reçoit un agent pour une tâche, avec la raison de chaque exclusion.",
  },
] as const;

function ConceptsStep() {
  return (
    <div className="grid gap-5">
      <StepHeader
        title="Trois notions à retenir"
        description="Tout le parcours ORBIT tient en un flux : des sources, une mémoire, un contexte."
      />
      <ol className="grid gap-3 sm:grid-cols-3">
        {CONCEPTS.map(({ icon: Icon, title, text }, index) => (
          <li key={title} className="grid content-start gap-2 rounded-lg border border-border bg-card p-4">
            <span className="flex items-center gap-2">
              <span className="flex size-8 items-center justify-center rounded-md bg-primary/10 text-primary">
                <Icon className="size-4" aria-hidden />
              </span>
              <span className="text-xs font-medium text-subtle-foreground">{index + 1}</span>
            </span>
            <h3 className="text-sm font-semibold">{title}</h3>
            <p className="text-[13px] leading-relaxed text-muted-foreground">{text}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}

function AccessStep({ clearance, isAdmin }: { clearance: number; isAdmin: boolean }) {
  const level = toClassification(clearance);
  return (
    <div className="grid gap-4">
      <StepHeader
        title="Votre niveau d’accès"
        description={
          <>
            Chaque contenu est classé de C0 à C3. Vous ne voyez, et vos agents ne reçoivent, que ce que votre
            habilitation autorise.
          </>
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">Votre habilitation :</span>
        <ClassificationBadge level={level} size="md" noTooltip />
        {isAdmin ? <span className="text-sm text-muted-foreground">· Administrateur de la plateforme</span> : null}
      </div>
      <ul className="grid gap-1.5" aria-label="Niveaux de classification">
        {CLASSIFICATIONS.map((value) => {
          const meta = CLASSIFICATION_META[value];
          const allowed = value <= level;
          return (
            <li
              key={value}
              className={cn(
                "flex items-center gap-3 rounded-lg border px-3 py-2 text-[13px]",
                allowed ? "border-border bg-card" : "border-dashed border-border bg-transparent opacity-60",
              )}
            >
              <ClassificationBadge level={value} noTooltip className="w-32 justify-center" />
              <span className="min-w-0 flex-1 text-muted-foreground">{meta.description}</span>
              <span className="shrink-0 text-xs font-medium text-subtle-foreground">
                {allowed ? "Accessible" : "Non accessible"}
              </span>
            </li>
          );
        })}
      </ul>
      <Alert tone={isSensitiveClassification(level) ? "amber" : "blue"} title="Données confidentielles ou secrètes">
        N’ingérez que des contenus que vous avez le droit de traiter. Un bandeau d’avertissement s’affiche dès qu’un
        contenu C2 (Confidentiel) ou C3 (Secret) est ingéré, affiché ou servi à un agent.
      </Alert>
    </div>
  );
}

function StartStep({ onDone }: { onDone: () => void }) {
  const { openCreateProject } = useShell();
  const projects = useProjects();
  const list = projects.data ?? [];
  const hasProjects = list.length > 0;

  return (
    <div className="grid gap-4">
      <StepHeader
        title="Premiers pas"
        description={
          hasProjects
            ? "Ouvrez un projet pour explorer ses sources, sa mémoire et ses contextes."
            : "Un projet réunit vos sources, votre mémoire et vos agents. Créez le vôtre pour commencer."
        }
      />

      {projects.isPending ? (
        <p className="text-sm text-muted-foreground">Chargement de vos projets…</p>
      ) : hasProjects ? (
        <ul className="grid gap-2">
          {list.slice(0, MAX_LISTED_PROJECTS).map((project) => (
            <li key={project.id}>
              <Button asChild variant="secondary" className="h-auto w-full justify-between px-3.5 py-2.5" onClick={onDone}>
                <Link href={projectHref(project.slug)}>
                  <span className="flex min-w-0 items-center gap-2.5">
                    <FolderKanban className="text-primary" aria-hidden />
                    <span className="truncate">{project.name}</span>
                  </span>
                  <ArrowRight aria-hidden />
                </Link>
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <Button
          size="lg"
          className="justify-self-start"
          leftIcon={<Plus aria-hidden />}
          onClick={() => {
            onDone();
            openCreateProject();
          }}
        >
          Créer mon premier projet
        </Button>
      )}

      <div className="grid gap-2 rounded-lg border border-border bg-surface-2/50 px-3.5 py-3 text-[13px] text-muted-foreground">
        <p className="flex items-center gap-2 font-medium text-foreground">
          <Rocket className="size-4 text-primary" aria-hidden />
          Bon à savoir
        </p>
        <p>
          <span className="font-medium text-foreground">Demander à ORBIT</span> répond à vos questions avec des
          citations issues de la mémoire du projet.
        </p>
        <p className="leading-relaxed">
          Recherchez n’importe quelle page avec <Kbd>⌘K</Kbd> (ou <Kbd>Ctrl+K</Kbd>). Retrouvez cette visite dans le
          menu de votre profil.
        </p>
      </div>
    </div>
  );
}
