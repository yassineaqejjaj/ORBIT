"use client";

import * as React from "react";
import { Bot, Wrench } from "lucide-react";

import { UserAvatar } from "@/components/domain/user-avatar";
import type { Member } from "@/lib/api/types";
import { getMeta, ACTOR_TYPE_META, type ActorType } from "@/lib/enums";
import { cn } from "@/lib/utils";

export interface MemoryActorProps {
  type: ActorType | string;
  id: string | null | undefined;
  label: string | null | undefined;
  /** Project members (resolves user names and avatar colors). */
  members?: readonly Member[];
  size?: "xs" | "sm";
  showName?: boolean;
  className?: string;
}

/** Avatar + label for a user, an agent or the system (memory events, "créé par"). */
export function MemoryActor({ type, id, label, members, size = "sm", showName = true, className }: MemoryActorProps) {
  const member = type === "user" && id ? members?.find((m) => m.user.id === id) : undefined;
  const typeLabel = getMeta(ACTOR_TYPE_META, type).label;
  const name = member?.user.full_name || label || (type === "system" ? "ORBIT (système)" : typeLabel);
  const box = size === "xs" ? "size-5 [&_svg]:size-3" : "size-6 [&_svg]:size-3.5";

  let avatar: React.ReactNode;
  if (type === "user") {
    avatar = (
      <UserAvatar
        size={size}
        user={member?.user ?? { full_name: label ?? undefined, email: undefined, avatar_color: undefined }}
      />
    );
  } else {
    avatar = (
      <span
        className={cn(
          "flex shrink-0 items-center justify-center rounded-full ring-1 ring-inset",
          box,
          type === "agent"
            ? "bg-teal-50 text-teal-700 ring-teal-600/20 dark:bg-teal-400/10 dark:text-teal-300 dark:ring-teal-400/25"
            : "bg-slate-100 text-slate-600 ring-slate-500/15 dark:bg-slate-400/10 dark:text-slate-300 dark:ring-slate-400/20",
        )}
        aria-hidden
      >
        {type === "agent" ? <Bot /> : <Wrench />}
      </span>
    );
  }

  if (!showName) {
    return (
      <span className={cn("inline-flex", className)} title={`${name} (${typeLabel})`}>
        {avatar}
      </span>
    );
  }
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1.5", className)}>
      {avatar}
      <span className="truncate text-[13px] font-medium text-foreground">{name}</span>
      {type !== "user" ? <span className="shrink-0 text-xs text-muted-foreground">· {typeLabel}</span> : null}
    </span>
  );
}
