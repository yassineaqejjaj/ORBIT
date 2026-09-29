"use client";

import * as React from "react";

import { SourceKindIcon } from "@/components/domain/source-kind-icon";
import { SimpleSelect, type SimpleSelectOption } from "@/components/ui/select";
import { SOURCE_KIND_META, SOURCE_KINDS, type SourceKind } from "@/lib/enums";

/** Kinds that can be created as a text note (`POST /documents/text`). */
export const NOTE_KINDS: readonly SourceKind[] = ["note", "ticket", "crm", "feedback", "agent_trace"];
/** Kinds accepted by the JSON/CSV importer (one row = one document). */
export const IMPORT_KINDS: readonly SourceKind[] = ["ticket", "crm", "feedback", "agent_trace", "note", "document"];

export interface SourceKindSelectProps {
  id?: string;
  value: SourceKind;
  onChange: (kind: SourceKind) => void;
  kinds?: readonly SourceKind[];
  disabled?: boolean;
  size?: "sm" | "md";
  className?: string;
  "aria-label"?: string;
}

/** Source kind picker with icons and French descriptions. */
export function SourceKindSelect({
  id,
  value,
  onChange,
  kinds = SOURCE_KINDS,
  disabled,
  size,
  className,
  "aria-label": ariaLabel,
}: SourceKindSelectProps) {
  const options = React.useMemo<SimpleSelectOption<SourceKind>[]>(
    () =>
      kinds.map((kind) => ({
        value: kind,
        label: SOURCE_KIND_META[kind].label,
        description: SOURCE_KIND_META[kind].description,
        icon: <SourceKindIcon kind={kind} size="sm" />,
      })),
    [kinds],
  );
  return (
    <SimpleSelect<SourceKind>
      id={id}
      value={value}
      onValueChange={onChange}
      options={options}
      disabled={disabled}
      size={size}
      className={className}
      aria-label={ariaLabel ?? "Type de source"}
    />
  );
}
