"use client";

import * as React from "react";
import { Hourglass, Lock, Save, SlidersHorizontal, Undo2, Info as InfoIcon, FolderKanban } from "lucide-react";
import { toast } from "sonner";

import { SourceKindIcon } from "@/components/domain/source-kind-icon";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CopyButton } from "@/components/ui/code-block";
import { Field, fieldDescribedBy } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { Textarea } from "@/components/ui/textarea";
import { useCurrentProject } from "@/hooks/use-current-project";
import { errorMessage } from "@/lib/api/client";
import { useUpdateProject } from "@/lib/api/hooks";
import type { Project, ProjectUpdateIn } from "@/lib/api/types";
import { SOURCE_KIND_META, SOURCE_KINDS, type SourceKind } from "@/lib/enums";
import { formatNumber, formatScore } from "@/lib/format";
import { cn } from "@/lib/utils";

const NAME_MAX = 120;
const DESCRIPTION_MAX = 2000;
const BUDGET_MIN = 500;
const BUDGET_MAX = 32_000;
const TTL_MIN = 1;
const TTL_MAX = 24 * 90;
const FRESHNESS_MIN = 1;
const FRESHNESS_MAX = 3650;

const DEFAULT_FRESHNESS: Record<SourceKind, number> = {
  document: 365,
  note: 120,
  ticket: 90,
  crm: 180,
  feedback: 180,
  agent_trace: 30,
  url: 180,
};

interface FormState {
  name: string;
  description: string;
  freshness: Record<SourceKind, string>;
  budget: string;
  minRelevance: number;
  ttl: string;
}

type Errors = Partial<Record<"name" | "description" | "budget" | "ttl" | SourceKind, string>>;

function toForm(project: Project): FormState {
  const freshness = {} as Record<SourceKind, string>;
  for (const kind of SOURCE_KINDS) {
    freshness[kind] = String(project.settings.freshness_days?.[kind] ?? DEFAULT_FRESHNESS[kind]);
  }
  return {
    name: project.name,
    description: project.description ?? "",
    freshness,
    budget: String(project.settings.default_token_budget),
    minRelevance: project.settings.min_relevance,
    ttl: String(project.settings.short_term_ttl_hours),
  };
}

function sameForm(a: FormState, b: FormState): boolean {
  return (
    a.name === b.name &&
    a.description === b.description &&
    a.budget === b.budget &&
    a.ttl === b.ttl &&
    Math.abs(a.minRelevance - b.minRelevance) < 1e-9 &&
    SOURCE_KINDS.every((k) => a.freshness[k] === b.freshness[k])
  );
}

function parseIntInRange(value: string, min: number, max: number): number | null {
  if (!/^\d+$/.test(value.trim())) return null;
  const n = Number.parseInt(value, 10);
  return n >= min && n <= max ? n : null;
}

function ttlHint(value: string): string {
  const n = parseIntInRange(value, TTL_MIN, TTL_MAX);
  if (n === null) return `Entre ${TTL_MIN} et ${formatNumber(TTL_MAX, 0)} heures.`;
  if (n % 24 === 0) return `Soit ${n / 24} jour${n / 24 > 1 ? "s" : ""} avant expiration des tours de session.`;
  return `Soit ${formatNumber(n / 24, 1)} jours avant expiration des tours de session.`;
}

/** "Projet" tab: identity, freshness policies per source kind, context assembly defaults (owner only). */
export function ProjectSettingsPanel() {
  const { project, slug, isOwner } = useCurrentProject();
  const update = useUpdateProject(slug, { meta: { silentError: true } });
  const initial = React.useMemo(() => toForm(project), [project]);
  const [form, setForm] = React.useState<FormState>(initial);
  const [errors, setErrors] = React.useState<Errors>({});
  const [formError, setFormError] = React.useState<string | null>(null);

  const dirty = !sameForm(form, initial);

  // Follow server updates while the user has no pending edits.
  const lastInitial = React.useRef(initial);
  React.useEffect(() => {
    if (lastInitial.current === initial) return;
    const prev = lastInitial.current;
    lastInitial.current = initial;
    setForm((current) => (sameForm(current, prev) ? initial : current));
  }, [initial]);

  const readOnly = !isOwner || update.isPending;

  const setFreshness = (kind: SourceKind, value: string) =>
    setForm((f) => ({ ...f, freshness: { ...f.freshness, [kind]: value } }));

  const validate = (): { errors: Errors; body: ProjectUpdateIn | null } => {
    const e: Errors = {};
    const name = form.name.trim();
    if (name.length < 1) e.name = "Le nom est obligatoire.";
    else if (name.length > NAME_MAX) e.name = `${NAME_MAX} caractères maximum.`;
    if (form.description.length > DESCRIPTION_MAX) e.description = `${DESCRIPTION_MAX} caractères maximum.`;
    const budget = parseIntInRange(form.budget, BUDGET_MIN, BUDGET_MAX);
    if (budget === null) e.budget = `Entre ${formatNumber(BUDGET_MIN, 0)} et ${formatNumber(BUDGET_MAX, 0)} tokens.`;
    const ttl = parseIntInRange(form.ttl, TTL_MIN, TTL_MAX);
    if (ttl === null) e.ttl = `Entre ${TTL_MIN} et ${formatNumber(TTL_MAX, 0)} heures.`;
    const freshness: Partial<Record<SourceKind, number>> = {};
    for (const kind of SOURCE_KINDS) {
      const days = parseIntInRange(form.freshness[kind], FRESHNESS_MIN, FRESHNESS_MAX);
      if (days === null) e[kind] = `${FRESHNESS_MIN}–${formatNumber(FRESHNESS_MAX, 0)} j`;
      else freshness[kind] = days;
    }
    if (Object.keys(e).length > 0 || budget === null || ttl === null) return { errors: e, body: null };

    const body: ProjectUpdateIn = {};
    if (name !== project.name) body.name = name;
    if (form.description !== (project.description ?? "")) body.description = form.description.trim();
    const settings: NonNullable<ProjectUpdateIn["settings"]> = {};
    const changedFreshness: Partial<Record<SourceKind, number>> = {};
    for (const kind of SOURCE_KINDS) {
      const days = freshness[kind];
      if (days !== undefined && days !== (project.settings.freshness_days?.[kind] ?? DEFAULT_FRESHNESS[kind])) {
        changedFreshness[kind] = days;
      }
    }
    if (Object.keys(changedFreshness).length > 0) settings.freshness_days = changedFreshness;
    if (budget !== project.settings.default_token_budget) settings.default_token_budget = budget;
    if (Math.abs(form.minRelevance - project.settings.min_relevance) > 1e-9) {
      settings.min_relevance = Math.round(form.minRelevance * 100) / 100;
    }
    if (ttl !== project.settings.short_term_ttl_hours) settings.short_term_ttl_hours = ttl;
    if (Object.keys(settings).length > 0) body.settings = settings;
    return { errors: e, body };
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!isOwner) return;
    const { errors: e, body } = validate();
    setErrors(e);
    setFormError(null);
    if (!body) return;
    if (Object.keys(body).length === 0) {
      setForm(initial);
      return;
    }
    try {
      const saved = await update.mutateAsync(body);
      setForm(toForm(saved));
      toast.success("Paramètres enregistrés", {
        description: "Les prochaines requêtes de contexte appliquent les nouvelles politiques.",
      });
    } catch (error) {
      setFormError(errorMessage(error));
    }
  };

  const reset = () => {
    setForm(initial);
    setErrors({});
    setFormError(null);
  };

  return (
    <form onSubmit={submit} className="grid gap-4" noValidate>
      {!isOwner ? (
        <Alert tone="neutral" icon={<Lock aria-hidden />}>
          Lecture seule : seuls les propriétaires du projet peuvent modifier ces paramètres.
        </Alert>
      ) : null}
      {formError ? <Alert tone="red">{formError}</Alert> : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FolderKanban className="size-4 text-muted-foreground" aria-hidden />
            Identité du projet
          </CardTitle>
          <CardDescription>Nom et description affichés aux membres et dans le sélecteur de projets.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,16rem)]">
            <Field id="settings-name" label="Nom" required error={errors.name}>
              <Input
                id="settings-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                invalid={Boolean(errors.name)}
                aria-describedby={fieldDescribedBy("settings-name", { error: errors.name })}
                readOnly={!isOwner}
                disabled={update.isPending}
                maxLength={NAME_MAX + 10}
              />
            </Field>
            <Field id="settings-slug" label="Identifiant" hint="Utilisé dans les URL, l'API et le serveur MCP.">
              <div className="flex items-center gap-1 rounded-md border border-input bg-muted/40 pl-3 pr-1">
                <span id="settings-slug" className="h-9 flex-1 truncate font-mono text-[13px] leading-9 text-foreground">
                  {project.slug}
                </span>
                <CopyButton value={project.slug} label="Copier l'identifiant" />
              </div>
            </Field>
          </div>
          <Field id="settings-description" label="Description" error={errors.description} labelAside={`${form.description.length}/${DESCRIPTION_MAX}`}>
            <Textarea
              id="settings-description"
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              rows={3}
              invalid={Boolean(errors.description)}
              readOnly={!isOwner}
              disabled={update.isPending}
            />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Hourglass className="size-4 text-muted-foreground" aria-hidden />
            Politiques de fraîcheur
          </CardTitle>
          <CardDescription>
            Âge maximal d&apos;un contenu, par type de source, au-delà duquel il est exclu du contexte avec le motif «&nbsp;Exclu —
            information périmée&nbsp;» (sauf décision validée).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2 xl:grid-cols-4">
            {SOURCE_KINDS.map((kind) => {
              const id = `settings-freshness-${kind}`;
              return (
                <div key={kind} className="grid gap-1.5">
                  <label htmlFor={id} className="flex items-center gap-2 text-[13px] font-medium text-foreground">
                    <SourceKindIcon kind={kind} size="sm" />
                    {SOURCE_KIND_META[kind].label}
                  </label>
                  <Input
                    id={id}
                    type="number"
                    inputMode="numeric"
                    min={FRESHNESS_MIN}
                    max={FRESHNESS_MAX}
                    value={form.freshness[kind]}
                    onChange={(e) => setFreshness(kind, e.target.value)}
                    invalid={Boolean(errors[kind])}
                    readOnly={!isOwner}
                    disabled={update.isPending}
                    size="sm"
                    rightSlot={<span className="pr-2 text-xs text-muted-foreground">jours</span>}
                    aria-describedby={errors[kind] ? `${id}-error` : undefined}
                  />
                  {errors[kind] ? (
                    <p id={`${id}-error`} className="text-xs font-medium text-destructive">
                      {errors[kind]}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <SlidersHorizontal className="size-4 text-muted-foreground" aria-hidden />
            Assemblage du contexte
          </CardTitle>
          <CardDescription>Valeurs par défaut appliquées aux requêtes des agents (surchargeables par requête).</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-6 lg:grid-cols-3">
          <Field
            id="settings-budget"
            label="Budget de tokens par défaut"
            error={errors.budget}
            hint={`Entre ${formatNumber(BUDGET_MIN, 0)} et ${formatNumber(BUDGET_MAX, 0)} tokens.`}
          >
            <Input
              id="settings-budget"
              type="number"
              inputMode="numeric"
              min={BUDGET_MIN}
              max={BUDGET_MAX}
              step={500}
              value={form.budget}
              onChange={(e) => setForm((f) => ({ ...f, budget: e.target.value }))}
              invalid={Boolean(errors.budget)}
              readOnly={!isOwner}
              disabled={update.isPending}
              rightSlot={<span className="pr-2 text-xs text-muted-foreground">tokens</span>}
            />
          </Field>
          <Field
            id="settings-relevance"
            label="Seuil de pertinence minimal"
            labelAside={<span className="font-mono text-[13px] font-semibold text-foreground">{formatScore(form.minRelevance)}</span>}
            hint="Sous ce score, un candidat est exclu (« pertinence insuffisante »)."
          >
            <Slider
              id="settings-relevance"
              min={0}
              max={1}
              step={0.05}
              value={[form.minRelevance]}
              onValueChange={(v) => setForm((f) => ({ ...f, minRelevance: v[0] ?? f.minRelevance }))}
              disabled={readOnly}
              aria-label="Seuil de pertinence minimal"
            />
            <div className="flex justify-between text-[11px] text-subtle-foreground">
              <span>0 · tout inclure</span>
              <span>1 · très strict</span>
            </div>
          </Field>
          <Field id="settings-ttl" label="Durée de la mémoire court terme" error={errors.ttl} hint={errors.ttl ? undefined : ttlHint(form.ttl)}>
            <Input
              id="settings-ttl"
              type="number"
              inputMode="numeric"
              min={TTL_MIN}
              max={TTL_MAX}
              value={form.ttl}
              onChange={(e) => setForm((f) => ({ ...f, ttl: e.target.value }))}
              invalid={Boolean(errors.ttl)}
              readOnly={!isOwner}
              disabled={update.isPending}
              rightSlot={<span className="pr-2 text-xs text-muted-foreground">heures</span>}
            />
          </Field>
        </CardContent>
      </Card>

      {isOwner ? (
        <div
          className={cn(
            "sticky bottom-4 z-20 flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 shadow-lg transition-opacity",
            dirty ? "border-border bg-popover opacity-100" : "pointer-events-none border-transparent bg-transparent opacity-0 shadow-none",
          )}
          aria-hidden={!dirty}
        >
          <InfoIcon className="size-4 text-muted-foreground" aria-hidden />
          <p className="text-[13px] text-foreground">Modifications non enregistrées</p>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={reset} disabled={!dirty || update.isPending} leftIcon={<Undo2 aria-hidden />}>
              Annuler
            </Button>
            <Button type="submit" size="sm" loading={update.isPending} disabled={!dirty} leftIcon={<Save aria-hidden />}>
              Enregistrer
            </Button>
          </div>
        </div>
      ) : null}
    </form>
  );
}
