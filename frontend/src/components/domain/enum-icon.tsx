import {
  BookOpen,
  Bot,
  Brain,
  Building2,
  CodeXml,
  Crown,
  Eye,
  FileText,
  FlaskConical,
  FolderKanban,
  Gavel,
  Globe,
  Heart,
  Landmark,
  Layers,
  ListChecks,
  MessageSquareQuote,
  MessagesSquare,
  Package,
  Palette,
  PencilLine,
  ScrollText,
  ClipboardCheck,
  ShieldAlert,
  StickyNote,
  Ticket,
  Timer,
  TriangleAlert,
  UserRound,
  Wrench,
  type LucideIcon,
  type LucideProps,
} from "lucide-react";

import type { IconName } from "@/lib/enums";

/** Resolves enum icon names (see `IconName` in lib/enums) to lucide components. */
export const ENUM_ICONS: Record<IconName, LucideIcon> = {
  FileText,
  StickyNote,
  Ticket,
  Building2,
  MessageSquareQuote,
  Bot,
  Globe,
  Timer,
  FolderKanban,
  UserRound,
  Landmark,
  Gavel,
  ListChecks,
  ShieldAlert,
  BookOpen,
  Heart,
  ScrollText,
  ClipboardCheck,
  TriangleAlert,
  Package,
  Palette,
  CodeXml,
  FlaskConical,
  Wrench,
  Crown,
  PencilLine,
  Eye,
  Layers,
  Brain,
  MessagesSquare,
};

export interface EnumIconProps extends LucideProps {
  name: IconName | undefined;
}

export function EnumIcon({ name, ...props }: EnumIconProps) {
  if (!name) return null;
  const Icon = ENUM_ICONS[name];
  return <Icon aria-hidden {...props} />;
}
