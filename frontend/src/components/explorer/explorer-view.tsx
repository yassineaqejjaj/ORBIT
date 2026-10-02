"use client";

import * as React from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, History, RefreshCw, ShieldCheck, Sparkles, Telescope, Timer, Waypoints } from "lucide-react";
import { toast } from "sonner";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/hooks/use-current-project";
import { useHotkey } from "@/hooks/use-hotkey";
import { errorMessage } from "@/lib/api/client";
import { queryKeys, useAgents, useAssembleContext, useContextRequest, useMe, useMembers } from "@/lib/api/hooks";
import type { ContextPackage, ContextRequestSummary, Page } from "@/lib/api/types";
import { CONTEXT_STAGES, CONTEXT_STAGE_META } from "@/lib/enums";
import {
  DEMO_TASK,
  HUMAN_AGENT,
  SELF_PRINCIPAL,
  buildContextRequest,
  clampBudget,
  defaultBudget,
  initialExplorerForm,
  parseVersionParam,
  validateExplorerForm,
  type ExplorerFormErrors,
  type ExplorerFormState,
} from "@/lib/explorer-utils";
import { ContextResult } from "./context-result";
import { HistoryDrawer } from "./history-drawer";
import { PipelineProgress } from "./pipeline-progress";
import type { ResultActor } from "./result-summary";
import { TaskComposer } from "./task-composer";

const NO_ERRORS: ExplorerFormErrors = {};

/** Who asked for a stored request, as listed by `GET /context/requests`. */
function actorFromSummary(r: ContextRequestSummary): ResultActor {
  return {
    label: r.agent?.name ?? r.user?.full_name ?? "Humain",
    isAgent: Boolean(r.agent),
    onBehalfOf: r.agent ? (r.user?.full_name ?? null) : null,
  };
}

function ResultSkeleton() {
  return (
    <div className="grid gap-4" aria-busy="true" aria-label="Chargement de la requête">
      <Skeleton className="h-40 rounded-xl" />
      <div className="grid gap-4 lg:grid-cols-5">
        <Skeleton className="h-64 rounded-xl lg:col-span-3" />
        <Skeleton className="h-64 rounded-xl lg:col-span-2" />
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-96 rounded-xl" />
        ))}
      </div>
    </div>
  );
}

function ExplorerIntro({ onTryDemo }: { onTryDemo: () => void }) {
  const promises = [
    { icon: <Waypoints aria-hidden />, title: "Pertinent", text: "Recherche hybride BM25 + k-NN, fusion RRF et reclassement." },
    { icon: <ShieldCheck aria-hidden />, title: "Gouverné", text: "ACL, classification C0–C3, fraîcheur, oubli : chaque exclusion est motivée." },
    { icon: <Timer aria-hidden />, title: "Expliqué", text: "Citations [S1]…, scores détaillés et temps de chaque étape." },
  ];
  return (
    <section
      aria-label="Présentation de l'explorateur"
      className="relative overflow-hidden rounded-xl border border-dashed border-border-strong bg-card/60 px-6 py-10"
    >
      <div className="bg-grid pointer-events-none absolute inset-0 opacity-40 [mask-image:radial-gradient(ellipse_at_center,black,transparent_70%)]" aria-hidden />
      <div className="relative mx-auto grid max-w-3xl justify-items-center gap-6 text-center">
        <span className="flex size-11 items-center justify-center rounded-xl border border-border bg-background text-brand shadow-xs" aria-hidden>
          <Telescope className="size-5" />
        </span>
        <div className="grid gap-1.5">
          <h2 className="text-base font-semibold tracking-tight">Ce qu&apos;un agent recevrait, et pourquoi</h2>
          <p className="text-[13px] leading-relaxed text-muted-foreground">
            Décrivez une tâche, choisissez l&apos;agent et le budget : ORBIT assemble le contexte gouverné et vous montre ce qui a
            été retenu, d&apos;où cela provient et ce qui a été exclu.
          </p>
        </div>
        <ol className="flex flex-wrap items-center justify-center gap-1.5 text-[11.5px] text-muted-foreground" aria-label="Étapes de l'assemblage">
          {CONTEXT_STAGES.map((stage, i) => (
            <li key={stage} className="flex items-center gap-1.5">
              <span className="rounded-md border border-border bg-background px-2 py-1 font-medium text-foreground/80" title={CONTEXT_STAGE_META[stage].description}>
                {CONTEXT_STAGE_META[stage].label}
              </span>
              {i < CONTEXT_STAGES.length - 1 ? <span className="text-subtle-foreground" aria-hidden>→</span> : null}
            </li>
          ))}
        </ol>
        <ul className="grid w-full gap-3 text-left sm:grid-cols-3">
          {promises.map((p) => (
            <li key={p.title} className="rounded-lg border border-border bg-background p-3">
              <p className="flex items-center gap-2 text-[13px] font-semibold text-foreground [&_svg]:size-4 [&_svg]:text-primary">
                {p.icon}
                {p.title}
              </p>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{p.text}</p>
            </li>
          ))}
        </ul>
        <Button variant="secondary" onClick={onTryDemo} leftIcon={<Sparkles aria-hidden />}>
          Essayer avec la tâche de démonstration
        </Button>
      </div>
    </section>
  );
}

/** Context explorer: compose a task, assemble a governed context and inspect every inclusion and exclusion. */
export function ExplorerView() {
  const { project, slug, isOwner } = useCurrentProject();
  const { data: me } = useMe();
  const router = useRouter();
  const queryClient = useQueryClient();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const requestParam = searchParams.get("request");
  const baseParam = searchParams.get("base");
  const versionParam = searchParams.get("version");
  // `?task=` prefills the task (e.g. « Votre premier contexte » at the end of the connector wizard).
  const taskParam = searchParams.get("task");

  const budgetDefault = defaultBudget(project);
  const [form, setForm] = React.useState<ExplorerFormState>(() => {
    const initial = initialExplorerForm(project, { name: baseParam, version: versionParam });
    return taskParam ? { ...initial, task: taskParam.slice(0, 4000) } : initial;
  });
  const [showErrors, setShowErrors] = React.useState(false);
  const [historyOpen, setHistoryOpen] = React.useState(false);
  const [activeRequestId, setActiveRequestId] = React.useState<string | null>(requestParam);
  const [actors, setActors] = React.useState<Record<string, ResultActor>>({});
  const taskRef = React.useRef<HTMLTextAreaElement>(null);
  const resultRef = React.useRef<HTMLDivElement>(null);

  const agents = useAgents(slug);
  const members = useMembers(slug, { enabled: isOwner });

  const [prevTaskParam, setPrevTaskParam] = React.useState(taskParam);
  if (taskParam !== prevTaskParam) {
    setPrevTaskParam(taskParam);
    if (taskParam) setForm((f) => ({ ...f, task: taskParam.slice(0, 4000) }));
  }

  // Follow `?base=&version=` (e.g. "Utiliser comme base" from the snapshots screen).
  const baseKey = `${baseParam ?? ""}@${versionParam ?? ""}`;
  const [prevBaseKey, setPrevBaseKey] = React.useState(baseKey);
  if (baseKey !== prevBaseKey) {
    setPrevBaseKey(baseKey);
    if (baseParam) setForm((f) => ({ ...f, baseName: baseParam, baseVersion: parseVersionParam(versionParam) }));
  }

  // Follow `?request=` (history, observability log, browser navigation).
  const [prevRequestParam, setPrevRequestParam] = React.useState(requestParam);
  if (requestParam !== prevRequestParam) {
    setPrevRequestParam(requestParam);
    setActiveRequestId(requestParam);
  }

  const errors = React.useMemo(() => (showErrors ? validateExplorerForm(form) : NO_ERRORS), [showErrors, form]);

  const assemble = useAssembleContext(slug, { meta: { silentError: true } });
  const detail = useContextRequest(slug, activeRequestId ?? undefined);

  const updateUrl = React.useCallback(
    (patch: Record<string, string | null>) => {
      const params = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(patch)) {
        if (value === null) params.delete(key);
        else params.set(key, value);
      }
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams],
  );

  const patchForm = React.useCallback((patch: Partial<ExplorerFormState>) => setForm((f) => ({ ...f, ...patch })), []);

  const scrollToResults = React.useCallback(() => {
    window.requestAnimationFrame(() => {
      const el = resultRef.current;
      if (!el) return;
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    });
  }, []);

  const describeActor = React.useCallback(
    (f: ExplorerFormState): ResultActor => {
      const agent = f.agentId !== HUMAN_AGENT ? agents.data?.find((a) => a.id === f.agentId) : undefined;
      const principal =
        isOwner && f.onBehalfOf !== SELF_PRINCIPAL ? members.data?.find((m) => m.user.id === f.onBehalfOf)?.user.full_name : null;
      return {
        label: agent ? agent.name : "Moi (humain)",
        isAgent: Boolean(agent),
        onBehalfOf: principal ?? (agent ? (me?.full_name ?? null) : null),
      };
    },
    [agents.data, members.data, isOwner, me?.full_name],
  );

  const submit = React.useCallback(() => {
    if (assemble.isPending) return;
    setShowErrors(true);
    const validation = validateExplorerForm(form);
    if (Object.keys(validation).length > 0) {
      if (validation.task) taskRef.current?.focus();
      return;
    }
    const body = buildContextRequest(form, { canActOnBehalf: isOwner });
    const actor = describeActor(form);
    assemble.mutate(body, {
      onSuccess: (pkg: ContextPackage) => {
        setActors((prev) => ({ ...prev, [pkg.request_id]: actor }));
        setActiveRequestId(pkg.request_id);
        updateUrl({ request: pkg.request_id });
        if (pkg.snapshot) {
          toast.success(`Snapshot « ${pkg.snapshot.name} » v${pkg.snapshot.version} enregistré.`);
          setForm((f) => ({ ...f, saveSnapshot: false }));
        }
        scrollToResults();
      },
    });
    scrollToResults();
  }, [assemble, form, isOwner, describeActor, updateUrl, scrollToResults]);

  useHotkey("Enter", submit, { mod: true, enabled: !historyOpen });

  const reset = () => {
    setForm(initialExplorerForm(project));
    setShowErrors(false);
    assemble.reset();
    if (baseParam || versionParam) updateUrl({ base: null, version: null });
    taskRef.current?.focus();
  };

  const tryDemo = () => {
    const firstProductAgent = agents.data?.find((a) => a.active && a.kind === "product");
    patchForm({
      task: DEMO_TASK,
      intent: "specification",
      ...(firstProductAgent ? { agentId: firstProductAgent.id } : {}),
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
    taskRef.current?.focus();
  };

  const reuse = (pkg: ContextPackage) => {
    patchForm({ task: pkg.task, intent: pkg.intent, tokenBudget: clampBudget(pkg.token_budget) });
    window.scrollTo({ top: 0, behavior: "smooth" });
    taskRef.current?.focus({ preventScroll: true });
    toast.message("Tâche reprise dans le composeur", { description: "Ajustez les paramètres puis assemblez à nouveau." });
  };

  const selectFromHistory = (r: ContextRequestSummary) => {
    setActors((prev) => ({ ...prev, [r.id]: actorFromSummary(r) }));
    setActiveRequestId(r.id);
    updateUrl({ request: r.id });
    setHistoryOpen(false);
    scrollToResults();
  };

  const closeActiveRequest = () => {
    setActiveRequestId(null);
    updateUrl({ request: null });
  };

  /**
   * The stored package does not carry its requester: reuse the one captured at submit/history time, or the row
   * already cached by the request lists (history drawer, observability log) when opened through `?request=`.
   */
  const actorFor = (requestId: string): ResultActor | null => {
    const known = actors[requestId];
    if (known) return known;
    const pages = queryClient.getQueriesData<Page<ContextRequestSummary>>({
      queryKey: queryKeys.project.context.requests(slug),
    });
    for (const [, page] of pages) {
      const hit = page?.items.find((r) => r.id === requestId);
      if (hit) return actorFromSummary(hit);
    }
    return null;
  };

  let result: React.ReactNode;
  if (assemble.isPending) {
    result = <PipelineProgress key={assemble.submittedAt} task={assemble.variables?.task ?? form.task} />;
  } else if (activeRequestId) {
    if (detail.data) {
      result = (
        <ContextResult
          pkg={detail.data}
          slug={slug}
          feedback={detail.data.feedback}
          actor={actorFor(detail.data.request_id)}
          minRelevance={project.settings?.min_relevance}
          onReuse={() => detail.data && reuse(detail.data)}
        />
      );
    } else if (detail.isError) {
      result = (
        <ErrorState
          error={detail.error}
          title={detail.error.isNotFound ? "Requête de contexte introuvable" : "Impossible de charger cette requête"}
          onRetry={() => void detail.refetch()}
          action={
            <Button variant="ghost" size="sm" onClick={closeActiveRequest}>
              Fermer
            </Button>
          }
        />
      );
    } else {
      result = <ResultSkeleton />;
    }
  } else {
    result = <ExplorerIntro onTryDemo={tryDemo} />;
  }

  return (
    <div className="grid grid-cols-1 gap-6">
      <PageHeader
        icon={<Telescope />}
        title="Contexte"
        description="Assemblez le contexte d'une tâche comme le recevrait un agent, et comprenez chaque inclusion et chaque exclusion."
        actions={
          <Button variant="secondary" size="sm" leftIcon={<History aria-hidden />} onClick={() => setHistoryOpen(true)}>
            Historique
          </Button>
        }
        className="pb-0"
      />

      <TaskComposer
        slug={slug}
        form={form}
        onChange={patchForm}
        errors={errors}
        onSubmit={submit}
        submitting={assemble.isPending}
        defaultBudget={budgetDefault}
        canActOnBehalf={isOwner}
        currentUserName={me?.full_name}
        currentUserId={me?.id}
        onReset={reset}
        taskRef={taskRef}
      />

      <div ref={resultRef} className="grid scroll-mt-20 gap-4">
        {assemble.isError ? (
          <Alert
            tone="red"
            title="L'assemblage du contexte a échoué"
            action={
              <Button variant="secondary" size="sm" onClick={submit} leftIcon={<RefreshCw aria-hidden />}>
                Réessayer
              </Button>
            }
          >
            {errorMessage(assemble.error)}
          </Alert>
        ) : null}
        {activeRequestId && !assemble.isPending && detail.data && detail.isRefetchError ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <ArrowDown className="size-3.5" aria-hidden />
            Résultat affiché depuis la réponse d&apos;assemblage (rechargement de la trace indisponible : {errorMessage(detail.error)}).
          </p>
        ) : null}
        {result}
      </div>

      <HistoryDrawer
        slug={slug}
        open={historyOpen}
        onOpenChange={setHistoryOpen}
        activeRequestId={activeRequestId}
        onSelect={selectFromHistory}
      />
    </div>
  );
}
