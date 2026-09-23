"use client";

import * as React from "react";
import { Layers } from "lucide-react";

import { SourceKindIcon } from "@/components/domain/source-kind-icon";
import { SimpleSelect, type SimpleSelectOption } from "@/components/ui/select";
import type { Source } from "@/lib/api/types";
import { getMeta, SOURCE_KIND_META, type SourceKind } from "@/lib/enums";
import { plural } from "@/lib/format";

export const DEFAULT_SOURCE = "__default__" as const;

export interface SourceSelectProps {
  id?: string;
  sources: readonly Source[] | undefined;
  /** Selected source id, or `DEFAULT_SOURCE`. */
  value: string;
  onChange: (value: string) => void;
  /** Only list sources of these kinds. */
  kinds?: readonly SourceKind[];
  /** Label of the "no explicit source" option. */
  defaultLabel?: string;
  defaultDescription?: string;
  disabled?: boolean;
  loading?: boolean;
  size?: "sm" | "md";
  className?: string;
  "aria-label"?: string;
}

/** Source picker with a leading "default source" entry (the API picks/creates the default source of a kind). */
export function SourceSelect({
  id,
  sources,
  value,
  onChange,
  kinds,
  defaultLabel = "Source par défaut",
  defaultDescription = "Déterminée automatiquement selon le type de contenu",
  disabled,
  loading,
  size,
  className,
  "aria-label": ariaLabel,
}: SourceSelectProps) {
  const options = React.useMemo<SimpleSelectOption<string>[]>(() => {
    const list = (sources ?? []).filter((s) => !kinds || kinds.includes(s.kind));
    return [
      { value: DEFAULT_SOURCE, label: defaultLabel, description: defaultDescription, icon: <Layers aria-hidden /> },
      ...list.map((s) => ({
        value: s.id,
        label: s.name,
        description: `${getMeta(SOURCE_KIND_META, s.kind).label} · ${plural(s.counts.documents, "document")}`,
        icon: <SourceKindIcon kind={s.kind} size="sm" />,
      })),
    ];
  }, [sources, kinds, defaultLabel, defaultDescription]);

  return (
    <SimpleSelect<string>
      id={id}
      value={value}
      onValueChange={onChange}
      options={options}
      disabled={disabled || loading}
      placeholder={loading ? "Chargement des sources…" : "Choisir une source"}
      size={size}
      className={className}
      aria-label={ariaLabel ?? "Source"}
    />
  );
}

/** `SourceSelect` value → API `source_id` (undefined for the default entry). */
export function sourceIdPayload(value: string): string | undefined {
  return value && value !== DEFAULT_SOURCE ? value : undefined;
}
