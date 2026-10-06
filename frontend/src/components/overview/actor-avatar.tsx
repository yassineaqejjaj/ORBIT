import { Bot, Cpu } from "lucide-react";

import { UserAvatar } from "@/components/domain/user-avatar";
import type { Member } from "@/lib/api/types";
import type { ActorType } from "@/lib/enums";
import { agentColorStyle } from "@/lib/agent-colors";
import { cn } from "@/lib/utils";

export interface ActorAvatarProps {
  actorType: ActorType | string;
  actorId: string | null;
  label: string | null | undefined;
  /** Project members, used to reuse the user's avatar color. */
  members?: readonly Member[];
  size?: "sm" | "md";
  /** Agent kind when known: the avatar takes its NOVA identity color (default: product coral). */
  agentKind?: string | null;
  className?: string;
}

/** Avatar for an audit actor: user initials, agent (bot) or system chip. */
export function ActorAvatar({ actorType, actorId, label, members, size = "md", agentKind, className }: ActorAvatarProps) {
  const box = size === "sm" ? "size-6 [&_svg]:size-3.5" : "size-8 [&_svg]:size-4";
  if (actorType === "agent") {
    return (
      <span
        className={cn(
          "agent-avatar flex shrink-0 items-center justify-center rounded-full",
          box,
          className,
        )}
        style={agentColorStyle(agentKind ?? "product")}
        title={label ?? "Agent"}
        aria-label={label ?? "Agent"}
        role="img"
      >
        <Bot aria-hidden />
      </span>
    );
  }
  if (actorType === "system") {
    return (
      <span
        className={cn(
          "flex shrink-0 items-center justify-center rounded-full bg-surface-3 text-muted-foreground ring-1 ring-inset ring-border",
          box,
          className,
        )}
        title={label ?? "Système ORBIT"}
        aria-label={label ?? "Système ORBIT"}
        role="img"
      >
        <Cpu aria-hidden />
      </span>
    );
  }
  const member = actorId ? members?.find((m) => m.user.id === actorId) : undefined;
  return (
    <UserAvatar
      user={member?.user ?? { full_name: label ?? undefined }}
      size={size === "sm" ? "sm" : "md"}
      className={cn("shrink-0", className)}
    />
  );
}
