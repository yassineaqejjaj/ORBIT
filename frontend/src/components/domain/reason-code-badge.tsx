import { Check, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { REASON_CODE_META, REASON_GROUP_META, type ReasonCode } from "@/lib/enums";

export interface ReasonCodeBadgeProps {
  code: ReasonCode | string;
  /** `reason_detail` from the API, shown in the tooltip. */
  detail?: string | null;
  /** Use the compact label ("Doublon") instead of the full one ("Exclu — doublon"). */
  short?: boolean;
  size?: "sm" | "md";
  className?: string;
}

/**
 * Governance reason badge. Tones: included = teal/green, governance (ACL/CLASSIFICATION/FORGOTTEN) = red,
 * quality (STALE/SUPERSEDED/CONFLICT/EXPIRED) = amber, efficiency (DUPLICATE/LOW_SCORE/BUDGET/SCOPE) = slate.
 */
export function ReasonCodeBadge({ code, detail, short = false, size = "sm", className }: ReasonCodeBadgeProps) {
  const meta = REASON_CODE_META[code as ReasonCode];
  if (!meta) {
    return (
      <Badge size={size} mono className={className}>
        {code}
      </Badge>
    );
  }
  const badge = (
    <Badge
      tone={meta.tone}
      size={size}
      icon={meta.included ? <Check aria-hidden /> : <X aria-hidden />}
      className={className}
    >
      {short ? meta.short : meta.label}
    </Badge>
  );
  const tooltip = (
    <span className="grid gap-0.5">
      <span className="font-medium">{meta.label}</span>
      {detail ? <span className="opacity-80">{detail}</span> : null}
      <span className="font-mono text-[10.5px] opacity-60">
        {code} · {REASON_GROUP_META[meta.group].label}
      </span>
    </span>
  );
  return (
    <SimpleTooltip content={tooltip}>
      <span className="inline-flex max-w-full">{badge}</span>
    </SimpleTooltip>
  );
}
