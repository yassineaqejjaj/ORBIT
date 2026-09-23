import { EnumIcon } from "@/components/domain/enum-icon";
import { Badge } from "@/components/ui/badge";
import { getMeta, MEMORY_SCOPE_META, type MemoryScope } from "@/lib/enums";

export interface ScopeBadgeProps {
  scope: MemoryScope | string;
  size?: "sm" | "md";
  variant?: "soft" | "outline";
  className?: string;
}

/** Memory scope: Court terme · Projet · Utilisateur · Long terme. */
export function ScopeBadge({ scope, size = "sm", variant = "outline", className }: ScopeBadgeProps) {
  const meta = getMeta(MEMORY_SCOPE_META, scope);
  return (
    <Badge
      tone={meta.tone}
      size={size}
      variant={variant}
      icon={<EnumIcon name={meta.icon} />}
      className={className}
      title={meta.description}
    >
      {meta.label}
    </Badge>
  );
}
