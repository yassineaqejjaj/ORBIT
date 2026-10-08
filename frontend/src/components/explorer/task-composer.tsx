"use client";

import * as React from "react";
import { Camera, ChevronDown, RotateCcw, Sparkles, UserRound, Wand2 } from "lucide-react";

import { EnumIcon } from "@/components/domain/enum-icon";
import { SourceKindIcon } from "@/components/domain/source-kind-icon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Kbd } from "@/components/ui/kbd";
import { Label } from "@/components/ui/label";
import { SimpleSelect, type SimpleSelectOption } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useAgents, useMembers, useSnapshots, useSnapshotVersions } from "@/lib/api/hooks";
import {
  AGENT_KIND_META,
  CLASSIFICATIONS,
  CLASSIFICATION_META,
  INTENTS,
  INTENT_META,
  MEMORY_SCOPES,
  MEMORY_SCOPE_META,
  ROLE_META,
  SOURCE_KINDS,
  SOURCE_KIND_META,
} from "@/lib/enums";
import {
  AUTO_INTENT,
  BUDGET_MAX,
  BUDGET_MIN,
  BUDGET_SLIDER_MAX,
  BUDGET_STEP,
  DEMO_TASK,
  HUMAN_AGENT,
  LATEST_VERSION,
  NO_BASE_SNAPSHOT,
  NO_CEILING,
  SELF_PRINCIPAL,
  TASK_MAX_LENGTH,
  clampBudget,
  isCeilingChoice,
  isIntentChoice,
  toggleInOrder,
  type ExplorerFormErrors,
  type ExplorerFormState,
} from "@/lib/explorer-utils";
import { agentColorStyle } from "@/lib/agent-colors";
import { formatDate, formatNumber } from "@/lib/format";
import { toneClasses } from "@/lib/tones";
import { cn, modKeyLabel } from "@/lib/utils";

export interface TaskComposerProps {
  slug: string;
  form: ExplorerFormState;
  onChange: (patch: Partial<ExplorerFormState>) => void;
  errors: ExplorerFormErrors;
  onSubmit: () => void;
  submitting: boolean;
  /** Project default token budget. */
  defaultBudget: number;
  /** Owners (and admins) may assemble on behalf of another member. */
  canActOnBehalf: boolean;
  currentUserName?: string | null;
  currentUserId?: string | null;
  onReset: () => void;
  taskRef?: React.Ref<HTMLTextAreaElement>;
}

function ToggleChip({
  pressed,
  onClick,
  icon,
  children,
  tone,
  disabled,
  title,
}: {
  pressed: boolean;
  onClick: () => void;
  icon?: React.ReactNode;
  children: React.ReactNode;
  tone: Parameters<typeof toneClasses>[0];
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-xs font-medium ring-1 ring-inset transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&_svg]:size-3.5",
        pressed ? toneClasses(tone).soft : "bg-background text-subtle-foreground ring-border hover:text-foreground",
      )}
    >
      {icon}
      {children}
    </button>
  );
}

/** Numeric budget input kept as a draft string while typing, committed (clamped) on blur / Enter. */
function BudgetInput({ value, onCommit, invalid }: { value: number; onCommit: (v: number) => void; invalid?: boolean }) {
  const [draft, setDraft] = React.useState(String(value));
  const [prev, setPrev] = React.useState(value);
  if (prev !== value) {
    setPrev(value);
    setDraft(String(value));
  }
  const commit = () => {
    const n = Number.parseInt(draft.replace(/\s/g, ""), 10);
    const next = Number.isFinite(n) ? clampBudget(n) : value;
    setDraft(String(next));
    if (next !== value) onCommit(next);
  };
  return (
    <Input
      id="explorer-budget-input"
      type="number"
      inputMode="numeric"
      size="sm"
      min={BUDGET_MIN}
      max={BUDGET_MAX}
      step={BUDGET_STEP}
      value={draft}
      invalid={invalid}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter" && !(e.metaKey || e.ctrlKey)) {
          e.preventDefault();
          commit();
        }
      }}
      className="w-24 text-right tabular-nums"
      aria-label="Budget de tokens (valeur exacte)"
    />
  );
}

/** "Tâche" composer: task, intent, acting agent, principal, budget, governance filters and snapshots. */
export function TaskComposer({
  slug,
  form,
  onChange,
  errors,
  onSubmit,
  submitting,
  defaultBudget,
  canActOnBehalf,
  currentUserName,
  currentUserId,
  onReset,
  taskRef,
}: TaskComposerProps) {
  const [advancedOpen, setAdvancedOpen] = React.useState(false);
  const agents = useAgents(slug);
  const members = useMembers(slug, { enabled: canActOnBehalf });
  const snapshots = useSnapshots(slug);
  const baseName = form.baseName !== NO_BASE_SNAPSHOT ? form.baseName : undefined;
  const versions = useSnapshotVersions(slug, baseName);
  const mod = React.useSyncExternalStore(
    () => () => undefined,
    () => modKeyLabel(),
    () => "Ctrl",
  );

  // Surface filter errors: open the advanced panel when one of its fields is invalid.
  const advancedError = Boolean(errors.scopes || errors.sourceKinds || errors.freshnessDays);
  React.useEffect(() => {
    if (advancedError) setAdvancedOpen(true);
  }, [advancedError]);

  const intentOptions: SimpleSelectOption[] = [
    { value: AUTO_INTENT, label: "Automatique", description: "Déduite des mots-clés de la tâche" },
    ...INTENTS.map((i) => ({ value: i, label: INTENT_META[i].label })),
  ];

  const activeAgents = (agents.data ?? []).filter((a) => a.active);
  const agentOptions: SimpleSelectOption[] = [
    { value: HUMAN_AGENT, label: "Moi (humain)", description: "Vos habilitations, détails d'audit complets", icon: <UserRound aria-hidden /> },
    ...activeAgents.map((a) => ({
      value: a.id,
      label: a.name,
      description: `${AGENT_KIND_META[a.kind]?.label ?? a.kind} · habilitation ${CLASSIFICATION_META[a.clearance]?.code ?? `C${a.clearance}`}`,
      icon: (
        <span className="agent-text flex" style={agentColorStyle(a.kind)}>
          <EnumIcon name={AGENT_KIND_META[a.kind]?.icon} />
        </span>
      ),
    })),
  ];
  // Keep a selected agent visible while the list loads (or if it was revoked meanwhile).
  if (form.agentId !== HUMAN_AGENT && !agentOptions.some((o) => o.value === form.agentId)) {
    agentOptions.push({ value: form.agentId, label: agents.isPending ? "Chargement…" : "Agent indisponible", disabled: true });
  }

  const memberOptions: SimpleSelectOption[] = [
    {
      value: SELF_PRINCIPAL,
      label: currentUserName ? `Moi — ${currentUserName}` : "Moi",
      description: "Utilisateur connecté (défaut)",
    },
    ...(members.data ?? [])
      .filter((m) => m.user.id !== currentUserId)
      .map((m) => ({
        value: m.user.id,
        label: m.user.full_name,
        description: `${ROLE_META[m.role].label} · habilitation ${CLASSIFICATION_META[m.user.clearance]?.code ?? `C${m.user.clearance}`}`,
      })),
  ];

  const snapshotList = snapshots.data ?? [];
  const snapshotOptions: SimpleSelectOption[] = [
    { value: NO_BASE_SNAPSHOT, label: "Aucun", description: "Nouvelle recherche complète" },
    ...snapshotList.map((s) => ({
      value: s.name,
      label: s.name,
      description: `v${s.latest_version} · ${formatDate(s.updated_at)}`,
      icon: <Camera aria-hidden />,
    })),
  ];
  if (baseName && !snapshotList.some((s) => s.name === baseName)) {
    snapshotOptions.push({ value: baseName, label: baseName, description: snapshots.isPending ? "Chargement…" : "Snapshot introuvable" });
  }

  const latestVersion = versions.data?.[0]?.version ?? snapshotList.find((s) => s.name === baseName)?.latest_version;
  const versionOptions: SimpleSelectOption[] = [
    { value: LATEST_VERSION, label: latestVersion ? `Dernière (v${latestVersion})` : "Dernière version" },
    ...(versions.data ?? []).map((v) => ({
      value: String(v.version),
      label: `v${v.version}`,
      description: `${formatDate(v.created_at)} · ${formatNumber(v.items_count, 0)} éléments`,
    })),
  ];
  if (form.baseVersion !== LATEST_VERSION && !versionOptions.some((o) => o.value === form.baseVersion)) {
    versionOptions.push({ value: form.baseVersion, label: `v${form.baseVersion}` });
  }

  const saveTarget = form.snapshotName.trim();
  // Snapshot names are stored lower-cased by the API.
  const existingTarget = snapshotList.find((s) => s.name.toLowerCase() === saveTarget.toLowerCase());

  const ceilingOptions: SimpleSelectOption[] = [
    { value: NO_CEILING, label: "Selon les habilitations", description: "min(utilisateur, agent)" },
    ...CLASSIFICATIONS.map((c) => ({
      value: String(c),
      label: `${CLASSIFICATION_META[c].code} · ${CLASSIFICATION_META[c].label}`,
      description: CLASSIFICATION_META[c].description,
    })),
  ];

  const filtersChanged =
    form.scopes.length !== MEMORY_SCOPES.length ||
    !form.includeSources ||
    form.sourceKinds.length !== SOURCE_KINDS.length ||
    form.maxClassification !== NO_CEILING ||
    form.freshnessDays.trim() !== "";

  const summaryChips = [
    form.scopes.length === MEMORY_SCOPES.length ? "Toutes les portées" : `${form.scopes.length}/${MEMORY_SCOPES.length} portées`,
    !form.includeSources
      ? "Sans sources"
      : form.sourceKinds.length === SOURCE_KINDS.length
        ? "Toutes les sources"
        : `${form.sourceKinds.length}/${SOURCE_KINDS.length} types de sources`,
    form.maxClassification === NO_CEILING
      ? "Classification selon habilitations"
      : `Plafond ${CLASSIFICATION_META[Number(form.maxClassification) as 0 | 1 | 2 | 3].code}`,
    form.freshnessDays.trim() ? `Fraîcheur ≤ ${form.freshnessDays.trim()} j` : "Fraîcheur : politiques du projet",
  ];

  return (
    <Card className="overflow-hidden rounded-composer">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit();
        }}
        noValidate
        aria-label="Composer une tâche"
      >
        <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="grid content-start gap-2">
            <div className="flex items-center justify-between gap-2">
              <Label htmlFor="explorer-task" className="text-sm font-semibold">
                Tâche
              </Label>
              {form.task.trim() !== DEMO_TASK ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="xs"
                  leftIcon={<Wand2 aria-hidden />}
                  onClick={() => onChange({ task: DEMO_TASK, intent: "specification" })}
                >
                  Exemple de démonstration
                </Button>
              ) : null}
            </div>
            <Textarea
              ref={taskRef}
              id="explorer-task"
              rows={6}
              value={form.task}
              onChange={(e) => onChange({ task: e.target.value })}
              placeholder={`Ex. ${DEMO_TASK}`}
              maxLength={TASK_MAX_LENGTH}
              invalid={Boolean(errors.task)}
              aria-describedby={errors.task ? "explorer-task-error" : "explorer-task-hint"}
              className="min-h-36 rounded-2xl px-4 py-3 text-[15px] leading-relaxed"
            />
            <div className="flex items-start justify-between gap-3 text-xs">
              {errors.task ? (
                <p id="explorer-task-error" role="alert" className="font-medium text-destructive">
                  {errors.task}
                </p>
              ) : (
                <p id="explorer-task-hint" className="text-muted-foreground">
                  Décrivez ce que l’agent doit produire&nbsp;: ORBIT sélectionne, gouverne et cite le contexte utile.
                </p>
              )}
              <span className="shrink-0 tabular-nums text-subtle-foreground">
                {formatNumber(form.task.length, 0)} / {formatNumber(TASK_MAX_LENGTH, 0)}
              </span>
            </div>
          </div>

          <div className="grid content-start gap-3.5">
            <Field id="explorer-intent" label="Intention">
              <SimpleSelect
                id="explorer-intent"
                size="sm"
                value={form.intent}
                onValueChange={(v) => isIntentChoice(v) && onChange({ intent: v })}
                options={intentOptions}
              />
            </Field>
            <Field id="explorer-agent" label="Agir en tant que">
              <SimpleSelect
                id="explorer-agent"
                size="sm"
                value={form.agentId}
                onValueChange={(v) => onChange({ agentId: v })}
                options={agentOptions}
              />
            </Field>
            {canActOnBehalf ? (
              <Field id="explorer-principal" label="Pour le compte de">
                <SimpleSelect
                  id="explorer-principal"
                  size="sm"
                  value={form.onBehalfOf}
                  onValueChange={(v) => onChange({ onBehalfOf: v })}
                  options={memberOptions}
                />
              </Field>
            ) : null}
            <div className="grid gap-1.5">
              <div className="flex items-center justify-between gap-2">
                <Label htmlFor="explorer-budget-input">Budget de tokens</Label>
                {form.tokenBudget !== defaultBudget ? (
                  <button
                    type="button"
                    className="text-[11.5px] font-medium text-primary hover:underline"
                    onClick={() => onChange({ tokenBudget: defaultBudget })}
                  >
                    Défaut projet ({formatNumber(defaultBudget, 0)})
                  </button>
                ) : (
                  <span className="text-[11.5px] text-subtle-foreground">défaut du projet</span>
                )}
              </div>
              <div className="flex items-center gap-3">
                <Slider
                  min={BUDGET_MIN}
                  max={BUDGET_SLIDER_MAX}
                  step={BUDGET_STEP}
                  value={[Math.min(form.tokenBudget, BUDGET_SLIDER_MAX)]}
                  onValueChange={(v) => onChange({ tokenBudget: clampBudget(v[0] ?? form.tokenBudget) })}
                  aria-label="Budget de tokens"
                  className="flex-1"
                />
                <BudgetInput value={form.tokenBudget} onCommit={(v) => onChange({ tokenBudget: v })} invalid={Boolean(errors.tokenBudget)} />
              </div>
              {errors.tokenBudget ? (
                <p role="alert" className="text-xs font-medium text-destructive">
                  {errors.tokenBudget}
                </p>
              ) : null}
            </div>
          </div>
        </div>

        <div className="border-t border-border px-5 py-3">
          <button
            type="button"
            onClick={() => setAdvancedOpen((v) => !v)}
            aria-expanded={advancedOpen}
            aria-controls="explorer-advanced"
            className="flex w-full flex-wrap items-center gap-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ChevronDown className={cn("size-4 text-subtle-foreground transition-transform", !advancedOpen && "-rotate-90")} aria-hidden />
            <span className="text-[13px] font-semibold text-foreground">Périmètre &amp; gouvernance</span>
            {filtersChanged ? <Badge tone="teal">Personnalisé</Badge> : null}
            {!advancedOpen ? (
              <span className="flex min-w-0 flex-wrap gap-1.5">
                {summaryChips.map((chip) => (
                  <Badge key={chip} variant="outline">
                    {chip}
                  </Badge>
                ))}
              </span>
            ) : null}
          </button>

          {advancedOpen ? (
            <div id="explorer-advanced" className="mt-4 grid gap-5 pb-1 md:grid-cols-2 xl:grid-cols-[1fr_1.4fr_1fr]">
              <fieldset className="grid content-start gap-2">
                <legend className="mb-2 text-[13px] font-medium">Portées de mémoire</legend>
                <div className="flex flex-wrap gap-1.5">
                  {MEMORY_SCOPES.map((scope) => {
                    const meta = MEMORY_SCOPE_META[scope];
                    return (
                      <ToggleChip
                        key={scope}
                        pressed={form.scopes.includes(scope)}
                        onClick={() => onChange({ scopes: toggleInOrder(form.scopes, MEMORY_SCOPES, scope) })}
                        icon={<EnumIcon name={meta.icon} />}
                        tone={meta.tone}
                        title={meta.description}
                      >
                        {meta.label}
                      </ToggleChip>
                    );
                  })}
                </div>
                {errors.scopes ? (
                  <p role="alert" className="text-xs font-medium text-destructive">
                    {errors.scopes}
                  </p>
                ) : null}
              </fieldset>

              <fieldset className="grid content-start gap-2">
                <legend className="sr-only">Sources</legend>
                <div className="mb-1 flex items-center justify-between gap-2">
                  <Label htmlFor="explorer-include-sources">Inclure les extraits de sources</Label>
                  <Switch
                    id="explorer-include-sources"
                    size="sm"
                    checked={form.includeSources}
                    onCheckedChange={(checked) => onChange({ includeSources: checked })}
                  />
                </div>
                <div className="flex flex-wrap gap-1.5" role="group" aria-label="Types de sources">
                  {SOURCE_KINDS.map((kind) => (
                    <ToggleChip
                      key={kind}
                      pressed={form.includeSources && form.sourceKinds.includes(kind)}
                      onClick={() => onChange({ sourceKinds: toggleInOrder(form.sourceKinds, SOURCE_KINDS, kind) })}
                      icon={<SourceKindIcon kind={kind} size="sm" />}
                      tone={SOURCE_KIND_META[kind].tone}
                      disabled={!form.includeSources}
                      title={SOURCE_KIND_META[kind].description}
                    >
                      {SOURCE_KIND_META[kind].label}
                    </ToggleChip>
                  ))}
                </div>
                {form.includeSources ? (
                  <div className="flex gap-3 text-[11.5px]">
                    <button type="button" className="font-medium text-primary hover:underline" onClick={() => onChange({ sourceKinds: [...SOURCE_KINDS] })}>
                      Toutes
                    </button>
                    <button type="button" className="font-medium text-muted-foreground hover:underline" onClick={() => onChange({ sourceKinds: [] })}>
                      Aucune
                    </button>
                  </div>
                ) : null}
                {errors.sourceKinds ? (
                  <p role="alert" className="text-xs font-medium text-destructive">
                    {errors.sourceKinds}
                  </p>
                ) : null}
              </fieldset>

              <div className="grid content-start gap-3.5 md:col-span-2 md:grid-cols-2 xl:col-span-1 xl:grid-cols-1">
                <Field id="explorer-ceiling" label="Classification maximale">
                  <SimpleSelect
                    id="explorer-ceiling"
                    size="sm"
                    value={form.maxClassification}
                    onValueChange={(v) => isCeilingChoice(v) && onChange({ maxClassification: v })}
                    options={ceilingOptions}
                  />
                </Field>
                <Field
                  id="explorer-freshness"
                  label="Fraîcheur maximale"
                  hint={errors.freshnessDays ? undefined : "Vide : politiques de fraîcheur du projet par type de source."}
                  error={errors.freshnessDays}
                >
                  <div className="flex items-center gap-2">
                    <Input
                      id="explorer-freshness"
                      type="number"
                      inputMode="numeric"
                      size="sm"
                      min={1}
                      value={form.freshnessDays}
                      onChange={(e) => onChange({ freshnessDays: e.target.value })}
                      placeholder="Politique du projet"
                      invalid={Boolean(errors.freshnessDays)}
                      className="w-40"
                    />
                    <span className="text-xs text-muted-foreground">jours</span>
                  </div>
                </Field>
              </div>
            </div>
          ) : null}
        </div>

        <div className="grid gap-4 border-t border-border px-5 py-4 md:grid-cols-2">
          <div className="grid content-start gap-1.5">
            <Label htmlFor="explorer-base">Partir d&apos;un snapshot</Label>
            <div className="flex gap-2">
              <SimpleSelect
                id="explorer-base"
                size="sm"
                value={form.baseName}
                onValueChange={(v) => onChange({ baseName: v, baseVersion: LATEST_VERSION })}
                options={snapshotOptions}
                className="flex-1"
              />
              <SimpleSelect
                size="sm"
                value={form.baseVersion}
                onValueChange={(v) => onChange({ baseVersion: v })}
                options={versionOptions}
                disabled={!baseName}
                className="w-40"
                aria-label="Version du snapshot de base"
              />
            </div>
            <p className="text-xs text-muted-foreground">
              {baseName
                ? "Les éléments du snapshot sont réinjectés (épinglés) puis complétés par une nouvelle recherche."
                : "Réutilisez le contexte commun d'un autre agent (ex. spec-atlas pour l'Agent Design)."}
            </p>
          </div>
          <div className="grid content-start gap-1.5">
            <div className="flex items-center justify-between gap-2">
              <Label htmlFor="explorer-progressive">Contexte progressif</Label>
              <Switch
                id="explorer-progressive"
                size="sm"
                checked={Boolean(form.progressive)}
                onCheckedChange={(checked) => onChange({ progressive: checked })}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              Résumé + index des sources et décisions (identifiants) ; l&apos;agent déplie le détail à la demande.
            </p>
          </div>
          <div className="grid content-start gap-1.5">
            <div className="flex items-center justify-between gap-2">
              <Label htmlFor="explorer-save-snapshot">Enregistrer comme snapshot</Label>
              <Switch
                id="explorer-save-snapshot"
                size="sm"
                checked={form.saveSnapshot}
                onCheckedChange={(checked) =>
                  onChange({ saveSnapshot: checked, ...(checked && !form.snapshotName && baseName ? { snapshotName: baseName } : {}) })
                }
              />
            </div>
            <Input
              id="explorer-snapshot-name"
              size="sm"
              value={form.snapshotName}
              onChange={(e) => onChange({ snapshotName: e.target.value, saveSnapshot: true })}
              placeholder="ex. spec-atlas"
              invalid={Boolean(errors.snapshotName)}
              aria-label="Nom du snapshot"
              aria-describedby="explorer-snapshot-help"
              leftIcon={<Camera aria-hidden />}
              className={cn(!form.saveSnapshot && "opacity-70")}
            />
            <p
              id="explorer-snapshot-help"
              role={errors.snapshotName ? "alert" : undefined}
              className={cn("text-xs", errors.snapshotName ? "font-medium text-destructive" : "text-muted-foreground")}
            >
              {errors.snapshotName ??
                (form.saveSnapshot && saveTarget
                  ? existingTarget
                    ? `Créera la version v${existingTarget.latest_version + 1} de « ${existingTarget.name} » (immuable).`
                    : `Créera le snapshot « ${saveTarget.toLowerCase()} » v1 (immuable).`
                  : "Contexte versionné et immuable, partageable avec les autres agents.")}
            </p>
          </div>
        </div>

        <div className="flex flex-col-reverse gap-3 border-t border-border bg-surface-2/50 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-1">
            <Button type="button" variant="ghost" size="sm" leftIcon={<RotateCcw aria-hidden />} onClick={onReset} disabled={submitting}>
              Réinitialiser
            </Button>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden items-center gap-1 text-xs text-subtle-foreground sm:inline-flex" aria-hidden>
              <Kbd>{mod}</Kbd>
              <Kbd>Entrée</Kbd>
            </span>
            <Button type="submit" loading={submitting} leftIcon={<Sparkles aria-hidden />} className="flex-1 rounded-full sm:flex-none">
              Assembler le contexte
            </Button>
          </div>
        </div>
      </form>
    </Card>
  );
}
