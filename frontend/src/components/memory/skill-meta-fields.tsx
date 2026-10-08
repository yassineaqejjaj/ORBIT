"use client";

import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import type { SkillMeta } from "@/lib/api/types";
import { AGENT_KIND_META, AGENT_KINDS, INTENT_META, INTENTS, type AgentKind, type Intent } from "@/lib/enums";
import { cn } from "@/lib/utils";

export type SkillMetaDraft = Pick<SkillMeta, "description" | "task_types" | "agent_kinds">;

export const EMPTY_SKILL_META: SkillMetaDraft = { description: "", task_types: [], agent_kinds: [] };

function Chips<T extends string>({
  label,
  values,
  options,
  labels,
  onChange,
}: {
  label: string;
  values: T[];
  options: readonly T[];
  labels: Record<T, { label: string }>;
  onChange: (next: T[]) => void;
}) {
  return (
    <fieldset className="grid gap-1.5">
      <legend className="mb-1 text-[13px] font-medium">{label}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((option) => {
          const on = values.includes(option);
          return (
            <button
              key={option}
              type="button"
              aria-pressed={on}
              onClick={() => onChange(on ? values.filter((v) => v !== option) : [...values, option])}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                on ? "border-primary bg-primary/10 text-foreground" : "border-border text-muted-foreground hover:bg-muted",
              )}
            >
              {labels[option].label}
            </button>
          );
        })}
      </div>
      <p className="text-xs text-muted-foreground">Aucune sélection : s&apos;applique à tous.</p>
    </fieldset>
  );
}

/** §D1 procedure metadata: served as an Agent Skill and injected in « Façons de faire ». */
export function SkillMetaFields({
  idPrefix,
  value,
  onChange,
}: {
  idPrefix: string;
  value: SkillMetaDraft;
  onChange: (next: SkillMetaDraft) => void;
}) {
  return (
    <div className="grid gap-3 rounded-md border border-dashed border-border p-3">
      <p className="text-xs text-muted-foreground">
        Les procédures sont servies aux agents comme <em>skills</em> (SKILL.md) et injectées dans la section « Façons de
        faire » du contexte selon le type de tâche et le type d&apos;agent.
      </p>
      <Field id={`${idPrefix}-skill-description`} label="Description du skill" hint="Quand l'agent doit l'appliquer.">
        <Input
          id={`${idPrefix}-skill-description`}
          value={value.description}
          maxLength={1024}
          onChange={(e) => onChange({ ...value, description: e.target.value })}
        />
      </Field>
      <Chips<Intent>
        label="Types de tâche"
        values={value.task_types}
        options={INTENTS}
        labels={INTENT_META}
        onChange={(task_types) => onChange({ ...value, task_types })}
      />
      <Chips<AgentKind>
        label="Types d'agent"
        values={value.agent_kinds}
        options={AGENT_KINDS}
        labels={AGENT_KIND_META}
        onChange={(agent_kinds) => onChange({ ...value, agent_kinds })}
      />
    </div>
  );
}
