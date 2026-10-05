"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Check, PlugZap, Sparkles, Telescope } from "lucide-react";

import { ClassificationBanner } from "@/components/domain/classification-banner";
import { projectHref } from "@/components/layout/nav";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage } from "@/lib/api/client";
import {
  isRunActive,
  useConnectorRun,
  useConnectorTypes,
  useCreateConnector,
  useTestConnectorCredentials,
  type Connector,
  type ConnectorConfig,
  type ConnectorTestResult,
  type ConnectorTypeInfo,
  type NativeConnectorType,
  type ScopeOption,
} from "@/lib/api/features-connectors";
import { CLASSIFICATION_META, CLASSIFICATIONS } from "@/lib/enums";
import { cn } from "@/lib/utils";
import { CONNECTOR_TYPE_ORDER, CONNECTOR_TYPES, presetDefaults, presetFieldsFilled, SCHEDULE_OPTIONS } from "./connector-meta";
import { McpFieldInputs, McpPresetHelp, McpToolsList } from "./mcp-fields";
import { ConnectorTypeIcon, McpBadge, RunProgress } from "./run-stats";

const STEPS = ["Type", "Identifiants", "Périmètre", "Synchronisation", "Premier contexte"] as const;

interface WizardState {
  /** Native type, or ``null`` with ``preset`` set for an MCP connector (F6). */
  type: NativeConnectorType | null;
  preset: ConnectorTypeInfo | null;
  /** MCP: non-secret field values (connection + scope) and secret fields. */
  values: Record<string, unknown>;
  secrets: Record<string, string>;
  name: string;
  config: ConnectorConfig;
  secret: string;
  test: ConnectorTestResult | null;
  selected: string[];
  jql: string;
  manualKeys: string;
  classification: number;
  restrict: boolean;
  schedule: string;
}

const INITIAL: WizardState = {
  type: null,
  preset: null,
  values: {},
  secrets: {},
  name: "",
  config: { deployment: "cloud" },
  secret: "",
  test: null,
  selected: [],
  jql: "",
  manualKeys: "",
  classification: 1,
  restrict: false,
  schedule: "60",
};

/** Onboarding wizard (docs/FEATURES.md F5): type → credentials + test → scope → first sync → first context. */
export function ConnectorWizard({
  slug,
  open,
  onClose,
  initialType,
}: {
  slug: string;
  open: boolean;
  onClose: () => void;
  initialType?: NativeConnectorType | null;
}) {
  const [step, setStep] = React.useState(0);
  const [state, setState] = React.useState<WizardState>(INITIAL);
  const [connector, setConnector] = React.useState<Connector | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const testCredentials = useTestConnectorCredentials(slug);
  const create = useCreateConnector(slug);
  const run = useConnectorRun(slug, connector?.id ?? null, connector?.last_run?.id ?? null);
  const types = useConnectorTypes(slug, open);
  const presets = (types.data ?? []).filter((t) => t.via_mcp);

  React.useEffect(() => {
    if (!open) return;
    setStep(initialType ? 1 : 0);
    setState({ ...INITIAL, type: initialType ?? null, name: initialType ? CONNECTOR_TYPES[initialType].label : "" });
    setConnector(null);
    setError(null);
  }, [open, initialType]);

  const patch = (next: Partial<WizardState>) => setState((s) => ({ ...s, ...next }));
  const patchConfig = (next: Partial<ConnectorConfig>) =>
    setState((s) => ({ ...s, config: { ...s.config, ...next }, test: null }));
  const meta = state.type ? CONNECTOR_TYPES[state.type] : null;
  const preset = state.preset;
  const patchValue = (key: string, value: unknown) =>
    setState((s) => ({
      ...s,
      values: { ...s.values, [key]: value },
      test: s.preset?.fields.find((f) => f.key === key)?.group === "scope" ? s.test : null,
    }));
  const patchSecret = (key: string, value: string) =>
    setState((s) => ({ ...s, secrets: { ...s.secrets, [key]: value }, test: null }));
  const mcpConfig = (): ConnectorConfig => ({ ...state.values, preset: preset?.preset ?? undefined });
  const mcpSecret = () =>
    JSON.stringify(Object.fromEntries(Object.entries(state.secrets).filter(([, v]) => v.trim() !== "")));

  const choosePreset = (info: ConnectorTypeInfo) => {
    patch({ type: null, preset: info, name: info.label, values: presetDefaults(info.fields), secrets: {}, test: null, selected: [] });
    setStep(1);
  };

  const runTest = () => {
    if (!state.type && !preset) return;
    setError(null);
    const body = preset
      ? { type: "mcp" as const, config: mcpConfig(), secret: mcpSecret() }
      : { type: state.type!, config: state.config, secret: state.secret };
    testCredentials
      .mutateAsync(body)
      .then((result) => {
        const jqlDefault = result.scope_options.find((o) => o.kind === "project");
        patch({ test: result, jql: state.jql || (jqlDefault ? `project = ${jqlDefault.id}` : "") });
      })
      .catch((err) => setError(errorMessage(err)));
  };

  const scopeConfig = (): ConnectorConfig => {
    const options = state.test?.scope_options ?? [];
    const chosen = options.filter((o) => state.selected.includes(o.id));
    const labels = chosen.map((o) => o.label);
    if (state.type === "jira") return { ...state.config, jql: state.jql.trim() };
    if (state.type === "confluence") {
      const manual = state.manualKeys.split(/[\s,;]+/).filter(Boolean);
      return { ...state.config, space_keys: [...chosen.map((o) => o.id), ...manual], scope_labels: [...labels, ...manual] };
    }
    const drives = chosen.filter((o) => o.kind === "drive");
    const sites = Array.from(new Set(drives.map((o) => o.parent_id).filter((id): id is string => Boolean(id))));
    return { ...state.config, drive_ids: drives.map((o) => o.id), site_ids: sites, scope_labels: labels };
  };

  const scopeValid = (() => {
    if (preset) return presetFieldsFilled(preset.fields, ["scope"], state.values, state.secrets);
    if (state.type === "jira") return state.jql.trim().length > 0;
    if (state.type === "confluence") return state.selected.length > 0 || state.manualKeys.trim().length > 0;
    return state.selected.length > 0;
  })();

  const startSync = () => {
    if (!state.type && !preset) return;
    setError(null);
    create
      .mutateAsync({
        type: preset ? "mcp" : state.type!,
        name: state.name.trim() || (preset ? preset.label : CONNECTOR_TYPES[state.type!].label),
        config: preset ? mcpConfig() : scopeConfig(),
        secret: preset ? mcpSecret() : state.secret,
        schedule_minutes: Number(state.schedule),
        default_classification: state.classification,
        restrict_to_editors: state.restrict,
        start_sync: true,
      })
      .then((created) => {
        setConnector(created);
        setStep(3);
      })
      .catch((err) => setError(errorMessage(err)));
  };

  const currentRun = run.data ?? connector?.last_run ?? null;
  const runDone = Boolean(currentRun && !isRunActive(currentRun));
  const credentialsFilled = preset
    ? presetFieldsFilled(preset.fields, ["secret", "connection"], state.values, state.secrets)
    : Boolean(
        meta &&
          meta.fields.every((f) => {
            if (!f.required) return true;
            if (f.deployment && f.deployment !== state.config.deployment) return true;
            const value = f.key === "secret" ? state.secret : (state.config[f.key] as string | undefined);
            return Boolean(value && String(value).trim());
          }),
      );

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent size="xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <PlugZap className="size-5 text-primary" aria-hidden />
            Connecter une source
          </DialogTitle>
          <DialogDescription>
            Les identifiants sont testés sans rien ingérer, puis chiffrés : ils ne sont jamais réaffichés.
          </DialogDescription>
        </DialogHeader>

        <ol className="flex flex-wrap items-center gap-1.5 text-xs" aria-label="Étapes de l'assistant">
          {STEPS.map((label, index) => (
            <li key={label} className="flex items-center gap-1.5">
              <span
                aria-current={index === step ? "step" : undefined}
                className={cn(
                  "flex items-center gap-1.5 rounded-full border px-2.5 py-1",
                  index === step
                    ? "border-primary bg-primary/10 font-medium text-primary"
                    : index < step
                      ? "border-border text-foreground"
                      : "border-border text-muted-foreground",
                )}
              >
                {index < step ? <Check className="size-3" aria-hidden /> : <span className="tabular-nums">{index + 1}</span>}
                {label}
              </span>
              {index < STEPS.length - 1 ? <span className="h-px w-3 bg-border" aria-hidden /> : null}
            </li>
          ))}
        </ol>

        <div className="min-h-64">
          {step === 0 ? (
            <div className="grid gap-3 sm:grid-cols-3">
              {CONNECTOR_TYPE_ORDER.map((type) => {
                const item = CONNECTOR_TYPES[type];
                return (
                  <button
                    key={type}
                    type="button"
                    onClick={() => {
                      patch({ type, preset: null, name: item.label, config: { deployment: "cloud" }, test: null, selected: [] });
                      setStep(1);
                    }}
                    className={cn(
                      "grid gap-2 rounded-lg border border-border bg-card p-4 text-left transition-colors hover:border-primary hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      state.type === type && "border-primary",
                    )}
                  >
                    <span className="flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                      <ConnectorTypeIcon type={type} className="size-5" />
                    </span>
                    <span className="font-medium">{item.label}</span>
                    <span className="text-xs text-muted-foreground">{item.tagline}</span>
                  </button>
                );
              })}
              <div className="grid gap-2 pt-2 sm:col-span-3">
                <p className="flex flex-wrap items-center gap-2 text-[13px] font-medium">
                  Via MCP <McpBadge />
                  <span className="font-normal text-muted-foreground">
                    serveurs Model Context Protocol éprouvés, exécutés par ORBIT avec vos identifiants
                  </span>
                </p>
                {types.isLoading ? (
                  <div className="grid gap-3 sm:grid-cols-3">
                    {[0, 1, 2].map((i) => (
                      <Skeleton key={i} className="h-24 rounded-lg" />
                    ))}
                  </div>
                ) : types.isError ? (
                  <Alert tone="red">{errorMessage(types.error)}</Alert>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-3">
                    {presets.map((info) => (
                      <button
                        key={info.preset}
                        type="button"
                        onClick={() => choosePreset(info)}
                        className={cn(
                          "grid content-start gap-2 rounded-lg border border-border bg-card p-4 text-left transition-colors hover:border-primary hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          preset?.preset === info.preset && "border-primary",
                        )}
                      >
                        <span className="flex items-center justify-between gap-2">
                          <span className="flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                            <ConnectorTypeIcon type="mcp" icon={info.icon} className="size-5" />
                          </span>
                          <McpBadge />
                        </span>
                        <span className="font-medium">{info.label}</span>
                        <span className="text-xs text-muted-foreground">{info.description}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : null}

          {step === 1 && preset ? (
            <div className="grid gap-4">
              <p className="text-sm text-muted-foreground">{preset.description}</p>
              <McpPresetHelp info={preset} />
              <Field id="wizard-name" label="Nom du connecteur" required>
                <Input id="wizard-name" maxLength={120} value={state.name} onChange={(e) => patch({ name: e.target.value })} />
              </Field>
              <McpFieldInputs
                fields={preset.fields}
                groups={["secret", "connection"]}
                values={state.values}
                secrets={state.secrets}
                onValue={patchValue}
                onSecret={patchSecret}
                idPrefix="wizard-mcp"
              />
              <div className="flex flex-wrap items-center gap-3">
                <Button type="button" variant="secondary" onClick={runTest} loading={testCredentials.isPending} disabled={!credentialsFilled}>
                  <PlugZap aria-hidden />
                  Tester la connexion
                </Button>
                {testCredentials.isPending ? (
                  <span className="text-xs text-muted-foreground" aria-live="polite">
                    Démarrage du serveur MCP et découverte des outils…
                  </span>
                ) : null}
              </div>
              {state.test ? (
                <div className="grid gap-3" aria-live="polite">
                  <Alert tone={state.test.ok ? "green" : "red"} title={state.test.ok ? "Connexion réussie" : "Échec du test"}>
                    {state.test.message}
                    {state.test.account ? <span className="block text-xs opacity-80">Serveur : {state.test.account}</span> : null}
                  </Alert>
                  <McpToolsList tools={state.test.tools} required={preset.required_tools} />
                </div>
              ) : null}
            </div>
          ) : null}

          {step === 1 && meta ? (
            <div className="grid gap-4">
              <p className="text-sm text-muted-foreground">{meta.description}</p>
              <Field id="wizard-name" label="Nom du connecteur" required>
                <Input id="wizard-name" maxLength={120} value={state.name} onChange={(e) => patch({ name: e.target.value })} />
              </Field>
              {meta.hasDeployment ? (
                <SegmentedControl
                  aria-label="Type de déploiement"
                  value={state.config.deployment ?? "cloud"}
                  onValueChange={(deployment) => patchConfig({ deployment })}
                  options={[
                    { value: "cloud", label: "Cloud (e-mail + jeton d'API)" },
                    { value: "datacenter", label: "Data Center (jeton personnel)" },
                  ]}
                />
              ) : null}
              <div className="grid gap-3 sm:grid-cols-2">
                {meta.fields
                  .filter((f) => !f.deployment || f.deployment === (state.config.deployment ?? "cloud"))
                  .map((f) => {
                    const id = `wizard-${f.key}`;
                    const value = f.key === "secret" ? state.secret : String(state.config[f.key] ?? "");
                    return (
                      <Field key={f.key} id={id} label={f.label} hint={f.hint} required={f.required}>
                        <Input
                          id={id}
                          type={f.type ?? "text"}
                          autoComplete={f.type === "password" ? "new-password" : "off"}
                          placeholder={f.placeholder}
                          value={value}
                          onChange={(e) =>
                            f.key === "secret"
                              ? patch({ secret: e.target.value, test: null })
                              : patchConfig({ [f.key]: e.target.value } as Partial<ConnectorConfig>)
                          }
                        />
                      </Field>
                    );
                  })}
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={runTest}
                  loading={testCredentials.isPending}
                  disabled={!credentialsFilled}
                >
                  <PlugZap aria-hidden />
                  Tester la connexion
                </Button>
                {testCredentials.isPending ? <span className="text-xs text-muted-foreground">Vérification…</span> : null}
              </div>
              {state.test ? (
                <Alert tone={state.test.ok ? "green" : "red"} title={state.test.ok ? "Connexion réussie" : "Échec du test"}>
                  {state.test.message}
                </Alert>
              ) : null}
            </div>
          ) : null}

          {step === 2 && (meta || preset) ? (
            <div className="grid gap-5">
              {preset ? <McpScope state={state} preset={preset} onValue={patchValue} /> : <ScopePicker state={state} patch={patch} />}
              <div className="grid gap-3 sm:grid-cols-2">
                <Field id="wizard-classification" label="Classification par défaut" hint="Jamais abaissée par la suite.">
                  <SimpleSelect
                    id="wizard-classification"
                    value={String(state.classification)}
                    onValueChange={(v) => patch({ classification: Number(v) })}
                    options={CLASSIFICATIONS.map((level) => ({
                      value: String(level),
                      label: `${CLASSIFICATION_META[level].code} · ${CLASSIFICATION_META[level].label}`,
                      description: CLASSIFICATION_META[level].description,
                    }))}
                  />
                </Field>
                <Field id="wizard-schedule" label="Synchronisation automatique">
                  <SimpleSelect
                    id="wizard-schedule"
                    value={state.schedule}
                    onValueChange={(schedule) => patch({ schedule })}
                    options={SCHEDULE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                  />
                </Field>
              </div>
              {state.classification >= 2 ? <ClassificationBanner level={state.classification} context="ingest" compact /> : null}
              <div className="flex items-start gap-3 rounded-lg border border-border px-3.5 py-3">
                <Switch id="wizard-restrict" checked={state.restrict} onCheckedChange={(restrict) => patch({ restrict })} />
                <div className="grid gap-0.5">
                  <Label htmlFor="wizard-restrict">Restreindre aux éditeurs</Label>
                  <p className="text-xs text-muted-foreground">
                    ACL <code>role:editor</code> au lieu de <code>project:*</code> : les lecteurs et les agents sans délégation
                    ne verront pas ces contenus.
                  </p>
                </div>
              </div>
            </div>
          ) : null}

          {step === 3 ? (
            <div className="grid gap-4">
              <p className="text-sm text-muted-foreground">
                Première synchronisation de « {connector?.name} » : les contenus rejoignent ensuite le pipeline d&apos;ingestion
                (extraction, caviardage PII, indexation).
              </p>
              {currentRun ? <RunProgress run={currentRun} /> : <Skeleton className="h-32 rounded-lg" />}
              {run.isError ? <Alert tone="red">{errorMessage(run.error)}</Alert> : null}
            </div>
          ) : null}

          {step === 4 && connector ? (
            <div className="grid gap-4">
              <div className="flex items-start gap-3 rounded-lg border border-border bg-muted/40 p-4">
                <Sparkles className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden />
                <div className="grid gap-1">
                  <p className="font-medium">Votre premier contexte</p>
                  <p className="text-sm text-muted-foreground">
                    Lancez l&apos;Explorateur avec une tâche suggérée pour voir comment ORBIT assemble un contexte gouverné à
                    partir de « {connector.name} ».
                  </p>
                  <blockquote className="mt-1 border-l-2 border-primary pl-3 text-sm italic">{connector.suggested_task}</blockquote>
                </div>
              </div>
              {currentRun?.status === "failed" ? (
                <Alert tone="amber" title="La synchronisation a échoué">
                  {currentRun.error} — corrigez le connecteur depuis sa fiche, puis relancez-la.
                </Alert>
              ) : null}
            </div>
          ) : null}
        </div>

        {error ? <Alert tone="red">{error}</Alert> : null}

        <DialogFooter className="sm:justify-between">
          <div>
            {step > 0 && step < 3 ? (
              <Button type="button" variant="ghost" onClick={() => setStep(step - 1)}>
                <ArrowLeft aria-hidden />
                Retour
              </Button>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            {step === 1 ? (
              <Button type="button" onClick={() => setStep(2)} disabled={!state.test?.ok || !state.name.trim()}>
                Choisir le périmètre
                <ArrowRight aria-hidden />
              </Button>
            ) : null}
            {step === 2 ? (
              <Button type="button" onClick={startSync} loading={create.isPending} disabled={!scopeValid}>
                Créer et synchroniser
                <ArrowRight aria-hidden />
              </Button>
            ) : null}
            {step === 3 ? (
              <>
                {!runDone ? (
                  <Button type="button" variant="secondary" onClick={() => setStep(4)}>
                    Continuer en arrière-plan
                  </Button>
                ) : null}
                <Button type="button" onClick={() => setStep(4)} disabled={!runDone}>
                  Continuer
                  <ArrowRight aria-hidden />
                </Button>
              </>
            ) : null}
            {step === 4 && connector ? (
              <>
                <Button type="button" variant="secondary" onClick={onClose}>
                  Fermer
                </Button>
                <Button asChild>
                  <Link href={`${projectHref(slug, "explorer")}?task=${encodeURIComponent(connector.suggested_task)}`}>
                    <Telescope aria-hidden />
                    Votre premier contexte
                  </Link>
                </Button>
              </>
            ) : null}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** MCP scope step: the preset's scope fields, plus the options returned by the test (Slack channels). */
function McpScope({
  state,
  preset,
  onValue,
}: {
  state: WizardState;
  preset: ConnectorTypeInfo;
  onValue: (key: string, value: unknown) => void;
}) {
  const channelOptions = (state.test?.scope_options ?? []).filter((o) => o.kind === "channel");
  const channels = Array.isArray(state.values.channels) ? (state.values.channels as string[]) : [];
  const toggle = (id: string) => onValue("channels", channels.includes(id) ? channels.filter((c) => c !== id) : [...channels, id]);
  return (
    <div className="grid gap-3">
      <McpFieldInputs
        fields={preset.fields}
        groups={["scope"]}
        values={state.values}
        secrets={state.secrets}
        onValue={onValue}
        onSecret={() => undefined}
        idPrefix="wizard-mcp"
      />
      {channelOptions.length ? (
        <fieldset className="grid gap-2">
          <legend className="mb-1 text-[13px] font-medium">Canaux proposés par le serveur</legend>
          <div className="grid max-h-48 gap-1.5 overflow-y-auto rounded-lg border border-border p-3 sm:grid-cols-2">
            {channelOptions.map((o) => (
              <ScopeCheckbox key={o.id} option={o} checked={channels.includes(o.id)} onToggle={() => toggle(o.id)} />
            ))}
          </div>
        </fieldset>
      ) : null}
    </div>
  );
}

function ScopePicker({ state, patch }: { state: WizardState; patch: (next: Partial<WizardState>) => void }) {
  const options = state.test?.scope_options ?? [];
  const toggle = (id: string) =>
    patch({ selected: state.selected.includes(id) ? state.selected.filter((s) => s !== id) : [...state.selected, id] });

  if (state.type === "jira") {
    const projects = options.filter((o) => o.kind === "project");
    return (
      <div className="grid gap-2">
        <Field
          id="wizard-jql"
          label="Requête JQL"
          required
          hint="Sans ORDER BY. Exemples : project = ORB, project in (ORB, OPS) AND statusCategory != Done"
        >
          <Textarea id="wizard-jql" rows={3} value={state.jql} onChange={(e) => patch({ jql: e.target.value })} className="font-mono text-[13px]" />
        </Field>
        {projects.length ? (
          <div className="flex flex-wrap gap-1.5" aria-label="Projets disponibles">
            {projects.slice(0, 20).map((p) => (
              <Button key={p.id} type="button" size="xs" variant="subtle" onClick={() => patch({ jql: `project = ${p.id}` })}>
                {p.label}
              </Button>
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  if (state.type === "confluence") {
    return (
      <fieldset className="grid gap-2">
        <legend className="mb-1 text-[13px] font-medium">Espaces à synchroniser</legend>
        {options.length ? (
          <div className="grid max-h-56 gap-1.5 overflow-y-auto rounded-lg border border-border p-3 sm:grid-cols-2">
            {options.map((o) => (
              <ScopeCheckbox key={o.id} option={o} checked={state.selected.includes(o.id)} onToggle={() => toggle(o.id)} />
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">Aucun espace listé : saisissez leurs clés ci-dessous.</p>
        )}
        <Field id="wizard-spaces" label="Autres clés d'espace" hint="Séparées par des virgules (ex. ORB, OPS)">
          <Input id="wizard-spaces" value={state.manualKeys} onChange={(e) => patch({ manualKeys: e.target.value })} />
        </Field>
      </fieldset>
    );
  }

  const sites = options.filter((o) => o.kind === "site");
  return (
    <fieldset className="grid gap-2">
      <legend className="mb-1 text-[13px] font-medium">Bibliothèques de documents</legend>
      {sites.length === 0 ? (
        <Alert tone="amber">Aucun site accessible avec ces identifiants (vérifiez la permission Sites.Read.All).</Alert>
      ) : (
        <div className="grid max-h-64 gap-3 overflow-y-auto rounded-lg border border-border p-3">
          {sites.map((site) => {
            const drives = options.filter((o) => o.kind === "drive" && o.parent_id === site.id);
            return (
              <div key={site.id} className="grid gap-1.5">
                <p className="text-[13px] font-medium">{site.label}</p>
                {drives.length ? (
                  <div className="grid gap-1.5 pl-1 sm:grid-cols-2">
                    {drives.map((d) => (
                      <ScopeCheckbox
                        key={d.id}
                        option={{ ...d, label: `${d.label}` }}
                        checked={state.selected.includes(d.id)}
                        onToggle={() => toggle(d.id)}
                      />
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">Aucune bibliothèque visible.</p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </fieldset>
  );
}

function ScopeCheckbox({ option, checked, onToggle }: { option: ScopeOption; checked: boolean; onToggle: () => void }) {
  const id = `scope-${option.kind}-${option.id}`;
  return (
    <div className="flex items-center gap-2">
      <Checkbox id={id} checked={checked} onCheckedChange={onToggle} />
      <Label htmlFor={id} className="min-w-0 truncate text-[13px] font-normal" title={option.description || option.label}>
        {option.label}
      </Label>
    </div>
  );
}
