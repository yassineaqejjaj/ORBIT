import {
  Archive,
  Ban,
  BadgeCheck,
  Camera,
  Radio,
  Clock3,
  EyeOff,
  FilePlus2,
  FileStack,
  GitCompareArrows,
  Plug,
  Repeat2,
  Scale,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import { CHANGE_TYPE_LABELS, type ChangeType } from "@/lib/api/features-feed";
import type { Tone } from "@/lib/enums";

export const CHANGE_TYPE_META: Record<ChangeType, { icon: LucideIcon; tone: Tone }> = {
  "memory.created": { icon: Sparkles, tone: "blue" },
  "memory.validated": { icon: BadgeCheck, tone: "green" },
  "memory.superseded": { icon: Repeat2, tone: "violet" },
  "memory.obsoleted": { icon: Archive, tone: "neutral" },
  "memory.forgotten": { icon: EyeOff, tone: "red" },
  "memory.conflict_detected": { icon: GitCompareArrows, tone: "amber" },
  "memory.conflict_resolved": { icon: Scale, tone: "teal" },
  "document.ingested": { icon: FilePlus2, tone: "sky" },
  "document.new_version": { icon: FileStack, tone: "sky" },
  "document.forgotten": { icon: Ban, tone: "red" },
  "document.stale": { icon: Clock3, tone: "orange" },
  "snapshot.created": { icon: Camera, tone: "pink" },
  "connector.synced": { icon: Plug, tone: "neutral" },
  "context.served": { icon: Radio, tone: "teal" },
};

export function changeMeta(type: string): { icon: LucideIcon; tone: Tone; label: string } {
  const meta = CHANGE_TYPE_META[type as ChangeType] ?? { icon: Sparkles, tone: "neutral" as Tone };
  return { ...meta, label: CHANGE_TYPE_LABELS[type as ChangeType] ?? type };
}

/** Filter families shown as chips above the timeline. */
export const CHANGE_FAMILIES: { value: string; label: string; types: ChangeType[] }[] = [
  {
    value: "decisions",
    label: "Décisions & mémoire",
    types: ["memory.created", "memory.validated", "memory.superseded", "memory.obsoleted", "memory.forgotten"],
  },
  { value: "conflicts", label: "Contradictions", types: ["memory.conflict_detected", "memory.conflict_resolved"] },
  {
    value: "documents",
    label: "Sources",
    types: ["document.ingested", "document.new_version", "document.forgotten", "document.stale"],
  },
  { value: "snapshots", label: "Snapshots", types: ["snapshot.created"] },
  { value: "connectors", label: "Connecteurs", types: ["connector.synced"] },
  { value: "contexts", label: "Contextes", types: ["context.served"] },
];
