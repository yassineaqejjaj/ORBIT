import { Lock, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { CLASSIFICATION_META, toClassification } from "@/lib/enums";
import { cn } from "@/lib/utils";

export interface ClassificationBadgeProps {
  /** 0..3 */
  level: number | null | undefined;
  /** Show "C2 · Confidentiel" (default) or only "C2". */
  showLabel?: boolean;
  size?: "sm" | "md";
  /** Prefix, e.g. "Habilitation" for clearances. */
  prefix?: string;
  /** Disable the explanatory tooltip. */
  noTooltip?: boolean;
  className?: string;
}

/** C0 Public · C1 Interne · C2 Confidentiel (amber) · C3 Secret (red). */
export function ClassificationBadge({
  level,
  showLabel = true,
  size = "sm",
  prefix,
  noTooltip,
  className,
}: ClassificationBadgeProps) {
  const lvl = toClassification(level);
  const meta = CLASSIFICATION_META[lvl];
  const badge = (
    <Badge
      tone={meta.tone}
      size={size}
      variant={lvl === 3 ? "solid" : "soft"}
      icon={meta.sensitive ? <Lock aria-hidden /> : lvl === 0 ? <ShieldCheck aria-hidden /> : undefined}
      className={cn("font-semibold", className)}
      aria-label={`${prefix ? `${prefix} ` : ""}Classification ${meta.code} — ${meta.label}`}
    >
      {prefix ? <span className="font-normal opacity-80">{prefix} </span> : null}
      {meta.code}
      {showLabel ? <span className="font-medium"> · {meta.label}</span> : null}
    </Badge>
  );
  if (noTooltip) return badge;
  return (
    <SimpleTooltip content={`${meta.code} — ${meta.label} : ${meta.description ?? ""}`}>
      <span className="inline-flex">{badge}</span>
    </SimpleTooltip>
  );
}
