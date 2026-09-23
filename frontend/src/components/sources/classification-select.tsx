"use client";

import * as React from "react";
import { Lock, ShieldCheck, Sparkles } from "lucide-react";

import { SimpleSelect, type SimpleSelectOption } from "@/components/ui/select";
import { CLASSIFICATIONS, CLASSIFICATION_META, type Classification } from "@/lib/enums";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

export const AUTO_CLASSIFICATION = "auto" as const;
export type ClassificationChoice = Classification | typeof AUTO_CLASSIFICATION;

export interface ClassificationSelectProps {
  id?: string;
  value: ClassificationChoice;
  onChange: (value: ClassificationChoice) => void;
  /** Offer "Automatique" (pipeline decides from source default, keywords and PII). */
  allowAuto?: boolean;
  autoLabel?: string;
  disabled?: boolean;
  size?: "sm" | "md";
  className?: string;
  "aria-label"?: string;
}

function LevelIcon({ level }: { level: Classification }) {
  const meta = CLASSIFICATION_META[level];
  return (
    <span className={cn("flex", toneClasses(meta.tone).text)}>
      {meta.sensitive ? <Lock aria-hidden /> : <ShieldCheck aria-hidden />}
    </span>
  );
}

/** C0–C3 selector (with optional "Automatique" choice) used by upload, note, import and edit dialogs. */
export function ClassificationSelect({
  id,
  value,
  onChange,
  allowAuto = false,
  autoLabel = "Automatique",
  disabled,
  size,
  className,
  "aria-label": ariaLabel,
}: ClassificationSelectProps) {
  const options = React.useMemo(() => {
    const levels: SimpleSelectOption<string>[] = CLASSIFICATIONS.map((level) => {
      const meta = CLASSIFICATION_META[level];
      return {
        value: String(level),
        label: `${meta.code} · ${meta.label}`,
        description: meta.description,
        icon: <LevelIcon level={level} />,
      };
    });
    if (!allowAuto) return levels;
    return [
      {
        value: AUTO_CLASSIFICATION,
        label: autoLabel,
        description: "Défaut de la source, mots-clés sensibles et données personnelles",
        icon: <Sparkles aria-hidden />,
      },
      ...levels,
    ];
  }, [allowAuto, autoLabel]);

  return (
    <SimpleSelect<string>
      id={id}
      value={String(value)}
      onValueChange={(v) => onChange(v === AUTO_CLASSIFICATION ? AUTO_CLASSIFICATION : (Number(v) as Classification))}
      options={options}
      disabled={disabled}
      size={size}
      className={className}
      aria-label={ariaLabel ?? "Classification"}
    />
  );
}

/** `ClassificationChoice` → API value (undefined for "auto"). */
export function classificationPayload(choice: ClassificationChoice): Classification | undefined {
  return choice === AUTO_CLASSIFICATION ? undefined : choice;
}
