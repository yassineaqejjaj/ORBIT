import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { cn, initials } from "@/lib/utils";

export interface UserAvatarUser {
  full_name?: string | null;
  email?: string | null;
  avatar_color?: string | null;
}

export interface UserAvatarProps {
  user: UserAvatarUser | null | undefined;
  size?: "xs" | "sm" | "md" | "lg";
  /** Render the name (and email when `withEmail`) next to the avatar. */
  showName?: boolean;
  withEmail?: boolean;
  className?: string;
}

const SIZES = {
  xs: "size-5 text-[9px]",
  sm: "size-6 text-[10px]",
  md: "size-8 text-[11px]",
  lg: "size-10 text-sm",
} as const;

const PALETTE = ["#0E9384", "#2A78D6", "#7A5AF8", "#DD2590", "#E04F16", "#0086C9", "#6172F3", "#15B79E"];

function colorFor(user: UserAvatarUser | null | undefined): string {
  const c = user?.avatar_color?.trim();
  if (c && /^#?[0-9a-f]{3,8}$/i.test(c)) return c.startsWith("#") ? c : `#${c}`;
  if (c && /^(rgb|hsl|oklch)\(/i.test(c)) return c;
  const seed = user?.email ?? user?.full_name ?? "";
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length] ?? PALETTE[0]!;
}

/** Initials avatar tinted with the user's `avatar_color`. */
export function UserAvatar({ user, size = "md", showName = false, withEmail = false, className }: UserAvatarProps) {
  const name = user?.full_name || user?.email || "Utilisateur";
  const avatar = (
    <Avatar className={cn(SIZES[size], !showName && className)} aria-label={showName ? undefined : name} title={showName ? undefined : name}>
      <AvatarFallback
        className="font-semibold text-white ring-1 ring-inset ring-black/5"
        style={{ backgroundColor: colorFor(user) }}
      >
        {initials(user?.full_name || user?.email)}
      </AvatarFallback>
    </Avatar>
  );
  if (!showName) return avatar;
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-2", className)}>
      {avatar}
      <span className="grid min-w-0 leading-tight">
        <span className="truncate text-[13px] font-medium text-foreground">{name}</span>
        {withEmail && user?.email ? <span className="truncate text-xs text-muted-foreground">{user.email}</span> : null}
      </span>
    </span>
  );
}
