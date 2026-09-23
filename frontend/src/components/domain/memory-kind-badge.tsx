import { EnumIcon } from "@/components/domain/enum-icon";
import { Badge } from "@/components/ui/badge";
import { getMeta, MEMORY_KIND_META, type MemoryKind } from "@/lib/enums";

export interface MemoryKindBadgeProps {
  kind: MemoryKind | string;
  size?: "sm" | "md";
  /** Hide the icon. */
  noIcon?: boolean;
  className?: string;
}

/** Décision · Besoin · Contrainte · Fait · Préférence · Synthèse · Risque */
export function MemoryKindBadge({ kind, size = "sm", noIcon, className }: MemoryKindBadgeProps) {
  const meta = getMeta(MEMORY_KIND_META, kind);
  return (
    <Badge
      tone={meta.tone}
      size={size}
      icon={noIcon ? undefined : <EnumIcon name={meta.icon} />}
      className={className}
    >
      {meta.label}
    </Badge>
  );
}
