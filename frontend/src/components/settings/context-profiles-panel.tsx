"use client";

import * as React from "react";
import { ArrowDown, ArrowUp, Lightbulb, RotateCcw, Save } from "lucide-react";
import { toast } from "sonner";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { ErrorState } from "@/components/ui/error-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/hooks/use-current-project";
import { errorMessage } from "@/lib/api/client";
import { useContextProfiles, useUpdateContextProfile } from "@/lib/api/hooks";
import type {
  ContextProfileIn,
  ContextProfileSection,
  ContextProfileView,
} from "@/lib/api/types";
import { AGENT_KIND_META } from "@/lib/enums";
import { formatNumber } from "@/lib/format";

const SECTION_LABELS: Record<ContextProfileSection, string> = {
  decisions: "Décisions en vigueur",
  requirements: "Besoins utilisateurs",
  constraints: "Contraintes & risques",
  facts: "Faits & connaissances",
  preferences: "Préférences utilisateur",
  sources: "Extraits de sources",
  session: "Session en cours",
};
const ALL_SECTIONS = Object.keys(SECTION_LABELS) as ContextProfileSection[];

interface Draft {
  /** Every section in display order, with its enabled flag. */
  order: { name: ContextProfileSection; enabled: boolean }[];
  budget: string;
  relevance: string;
  sufficient: string;
}

function toDraft(
  p: Pick<
    ContextProfileView,
    "sections" | "token_budget" | "min_relevance" | "sufficient_threshold"
  >,
): Draft {
  const rest = ALL_SECTIONS.filter((s) => !p.sections.includes(s));
  return {
    order: [
      ...p.sections.map((name) => ({ name, enabled: true })),
      ...rest.map((name) => ({ name, enabled: false })),
    ],
    budget: p.token_budget == null ? "" : String(p.token_budget),
    relevance: p.min_relevance == null ? "" : String(p.min_relevance),
    sufficient:
      p.sufficient_threshold == null ? "" : String(p.sufficient_threshold),
  };
}

function parseNumber(
  value: string,
  min: number,
  max: number,
): number | null | undefined {
  if (value.trim() === "") return null;
  const n = Number(value.replace(",", "."));
  return Number.isFinite(n) && n >= min && n <= max ? n : undefined;
}

function ProfileCard({
  profile,
  slug,
  canEdit,
}: {
  profile: ContextProfileView;
  slug: string;
  canEdit: boolean;
}) {
  const [draft, setDraft] = React.useState<Draft>(() => toDraft(profile));
  React.useEffect(() => setDraft(toDraft(profile)), [profile]);
  const update = useUpdateContextProfile(slug);
  const meta = AGENT_KIND_META[profile.kind];
  const budget = parseNumber(draft.budget, 500, 32_000);
  const relevance = parseNumber(draft.relevance, 0, 1);
  const sufficient = parseNumber(draft.sufficient, 0, 1);
  const sections = draft.order.filter((s) => s.enabled).map((s) => s.name);
  const valid =
    budget !== undefined &&
    relevance !== undefined &&
    sufficient !== undefined &&
    sections.length > 0;
  const suggestion = profile.suggestion;
  const hasSuggestion = Object.keys(suggestion.changes).length > 0;

  const move = (index: number, delta: number) =>
    setDraft((d) => {
      const order = [...d.order];
      const target = index + delta;
      if (target < 0 || target >= order.length) return d;
      const current = order[index];
      const other = order[target];
      if (!current || !other) return d;
      order[index] = other;
      order[target] = current;
      return { ...d, order };
    });

  const save = (body: ContextProfileIn | null) =>
    update.mutate(
      { kind: profile.kind, body },
      {
        onSuccess: () =>
          toast.success(
            body
              ? `Profil « ${meta.label} » enregistré`
              : `Profil « ${meta.label} » réinitialisé`,
          ),
        onError: (error) => toast.error(errorMessage(error)),
      },
    );

  const applySuggestion = () => {
    const next = toDraft({
      sections: suggestion.changes.sections ?? sections,
      token_budget: suggestion.changes.token_budget ?? budget ?? null,
      min_relevance: suggestion.changes.min_relevance ?? relevance ?? null,
      sufficient_threshold: sufficient ?? null,
    });
    setDraft(next);
  };

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div className="grid gap-1">
          <CardTitle className="flex items-center gap-2">
            {meta.label}
            {profile.customized ? (
              <Badge tone="teal" size="sm">
                Personnalisé
              </Badge>
            ) : (
              <Badge tone="neutral" size="sm">
                Par défaut
              </Badge>
            )}
          </CardTitle>
          <CardDescription className="text-xs">
            Appliqué aux agents « {meta.label} » et à l&apos;Explorateur en mode
            « agir en tant que ». Les paramètres explicites d&apos;une requête
            restent prioritaires.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-4 lg:grid-cols-[1fr_16rem]">
          <fieldset className="grid gap-1.5" disabled={!canEdit}>
            <legend className="mb-1 text-[13px] font-medium text-foreground">
              Sections servies et ordre
            </legend>
            <ol className="grid gap-1">
              {draft.order.map((section, index) => (
                <li
                  key={section.name}
                  className="flex items-center gap-2 rounded-md border border-border bg-surface-2/40 px-2 py-1.5 text-sm"
                >
                  <Checkbox
                    id={`profile-${profile.kind}-${section.name}`}
                    checked={section.enabled}
                    onCheckedChange={(checked) =>
                      setDraft((d) => ({
                        ...d,
                        order: d.order.map((s) =>
                          s.name === section.name
                            ? { ...s, enabled: checked === true }
                            : s,
                        ),
                      }))
                    }
                  />
                  <label
                    htmlFor={`profile-${profile.kind}-${section.name}`}
                    className="flex-1 truncate"
                  >
                    {SECTION_LABELS[section.name]}
                  </label>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label={`Monter « ${SECTION_LABELS[section.name]} »`}
                    onClick={() => move(index, -1)}
                    disabled={!canEdit || index === 0}
                  >
                    <ArrowUp aria-hidden />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label={`Descendre « ${SECTION_LABELS[section.name]} »`}
                    onClick={() => move(index, 1)}
                    disabled={!canEdit || index === draft.order.length - 1}
                  >
                    <ArrowDown aria-hidden />
                  </Button>
                </li>
              ))}
            </ol>
          </fieldset>
          <div className="grid content-start gap-3">
            <Field
              id={`profile-${profile.kind}-budget`}
              label="Budget de tokens"
              hint={`Vide = défaut du projet (défaut du type : ${profile.default.token_budget ? formatNumber(profile.default.token_budget, 0) : "projet"})`}
              error={budget === undefined ? "Entre 500 et 32 000" : undefined}
            >
              <Input
                id={`profile-${profile.kind}-budget`}
                inputMode="numeric"
                value={draft.budget}
                disabled={!canEdit}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, budget: e.target.value }))
                }
              />
            </Field>
            <Field
              id={`profile-${profile.kind}-relevance`}
              label="Seuil de pertinence"
              hint="0 à 1 ; vide = seuil du projet"
              error={relevance === undefined ? "Entre 0 et 1" : undefined}
            >
              <Input
                id={`profile-${profile.kind}-relevance`}
                inputMode="decimal"
                value={draft.relevance}
                disabled={!canEdit}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, relevance: e.target.value }))
                }
              />
            </Field>
            <Field
              id={`profile-${profile.kind}-sufficient`}
              label="Seuil de suffisance"
              hint="Score à partir duquel le contexte est « suffisant »"
              error={sufficient === undefined ? "Entre 0 et 1" : undefined}
            >
              <Input
                id={`profile-${profile.kind}-sufficient`}
                inputMode="decimal"
                value={draft.sufficient}
                disabled={!canEdit}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, sufficient: e.target.value }))
                }
              />
            </Field>
          </div>
        </div>

        <Alert
          tone={hasSuggestion ? "amber" : "neutral"}
          icon={<Lightbulb aria-hidden />}
          title={
            hasSuggestion
              ? "Ajustement suggéré d'après les retours"
              : `Retours analysés : ${suggestion.feedback_count}${suggestion.avg_rating != null ? ` · note moyenne ${formatNumber(suggestion.avg_rating, 1)}/5` : ""}`
          }
          action={
            hasSuggestion && canEdit ? (
              <Button variant="secondary" size="xs" onClick={applySuggestion}>
                Reprendre la suggestion
              </Button>
            ) : undefined
          }
        >
          <ul className="grid gap-0.5 text-xs">
            {suggestion.rationale.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </Alert>

        {canEdit ? (
          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              leftIcon={<RotateCcw aria-hidden />}
              disabled={!profile.customized || update.isPending}
              onClick={() => save(null)}
            >
              Réinitialiser
            </Button>
            <Button
              size="sm"
              leftIcon={<Save aria-hidden />}
              loading={update.isPending}
              disabled={!valid}
              onClick={() =>
                valid &&
                save({
                  sections,
                  token_budget: budget ?? null,
                  min_relevance: relevance ?? null,
                  sufficient_threshold: sufficient ?? null,
                })
              }
            >
              Enregistrer
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

/** §C3 context profiles per agent kind: budget, sections, order and thresholds, with suggestions. */
export function ContextProfilesPanel() {
  const { slug, isOwner } = useCurrentProject();
  const profiles = useContextProfiles(slug);
  if (profiles.isError) {
    return (
      <ErrorState
        title="Profils indisponibles"
        error={profiles.error}
        onRetry={() => profiles.refetch()}
      />
    );
  }
  if (!profiles.data) {
    return (
      <div className="grid gap-4">
        {Array.from({ length: 2 }, (_, i) => (
          <Skeleton key={i} className="h-72 w-full" />
        ))}
      </div>
    );
  }
  return (
    <div className="grid gap-4">
      {profiles.data.map((profile) => (
        <ProfileCard
          key={profile.kind}
          profile={profile}
          slug={slug}
          canEdit={isOwner}
        />
      ))}
    </div>
  );
}
