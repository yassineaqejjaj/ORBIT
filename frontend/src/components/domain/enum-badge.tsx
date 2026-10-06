import { EnumIcon } from "@/components/domain/enum-icon";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { agentColorStyle } from "@/lib/agent-colors";
import {
  AGENT_KIND_META,
  CANDIDATE_TYPE_META,
  getMeta,
  INTENT_META,
  JOB_KIND_META,
  MEMORY_EVENT_META,
  RELATION_TYPE_META,
  ROLE_META,
  type EnumMeta,
} from "@/lib/enums";
import { cn } from "@/lib/utils";

export interface EnumBadgeProps extends Omit<BadgeProps, "tone" | "children"> {
  meta: Record<string, EnumMeta>;
  value: string | null | undefined;
  withIcon?: boolean;
}

/** Generic badge for any `*_META` enum record. */
export function EnumBadge({ meta, value, withIcon = true, ...props }: EnumBadgeProps) {
  const m = getMeta(meta, value);
  return (
    <Badge tone={m.tone} icon={withIcon && m.icon ? <EnumIcon name={m.icon} /> : undefined} title={m.description} {...props}>
      {m.label}
    </Badge>
  );
}

type ValueBadgeProps = Omit<EnumBadgeProps, "meta">;

export const RoleBadge = (props: ValueBadgeProps) => <EnumBadge meta={ROLE_META} {...props} />;
export const IntentBadge = (props: ValueBadgeProps) => <EnumBadge meta={INTENT_META} withIcon={false} {...props} />;
/** Agent kind, in its NOVA identity color (lib/agent-colors.ts). */
export const AgentKindBadge = ({ className, style, ...props }: ValueBadgeProps) => (
  <EnumBadge
    meta={AGENT_KIND_META}
    className={cn("agent-avatar ring-0", className)}
    style={{ ...agentColorStyle(props.value), ...style }}
    {...props}
  />
);
export const JobKindBadge = (props: ValueBadgeProps) => <EnumBadge meta={JOB_KIND_META} withIcon={false} {...props} />;
export const RelationTypeBadge = (props: ValueBadgeProps) => (
  <EnumBadge meta={RELATION_TYPE_META} withIcon={false} variant="outline" {...props} />
);
export const MemoryEventBadge = (props: ValueBadgeProps) => <EnumBadge meta={MEMORY_EVENT_META} withIcon={false} {...props} />;
export const CandidateTypeBadge = (props: ValueBadgeProps) => (
  <EnumBadge meta={CANDIDATE_TYPE_META} variant="outline" {...props} />
);
