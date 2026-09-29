import { EnumIcon } from "@/components/domain/enum-icon";
import { SourceKindIcon } from "@/components/domain/source-kind-icon";
import {
  CANDIDATE_TYPE_META,
  MEMORY_KIND_META,
  SOURCE_KIND_META,
  getMeta,
  type CandidateType,
  type IconName,
  type Tone,
} from "@/lib/enums";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

export interface ItemTypeDescriptor {
  candidate_type: CandidateType | string;
  source_kind?: string | null;
  memory_kind?: string | null;
}

/** French label of what a candidate is: "Décision", "Ticket", "Session"… */
export function itemTypeLabel(item: ItemTypeDescriptor): string {
  if (item.candidate_type === "memory" && item.memory_kind) return getMeta(MEMORY_KIND_META, item.memory_kind).label;
  if (item.candidate_type === "chunk" && item.source_kind) return getMeta(SOURCE_KIND_META, item.source_kind).label;
  return getMeta(CANDIDATE_TYPE_META, item.candidate_type).label;
}

function iconFor(item: ItemTypeDescriptor): { icon: IconName; tone: Tone } {
  if (item.candidate_type === "memory") {
    const meta = item.memory_kind ? MEMORY_KIND_META[item.memory_kind as keyof typeof MEMORY_KIND_META] : undefined;
    return meta ? { icon: meta.icon, tone: meta.tone } : { icon: "Brain", tone: "teal" };
  }
  if (item.candidate_type === "session") return { icon: "MessagesSquare", tone: "sky" };
  return { icon: "Layers", tone: "blue" };
}

/** Tinted square chip with the icon of a context candidate (source kind for chunks, memory kind for memory). */
export function ItemTypeIcon({ item, size = "md", className }: { item: ItemTypeDescriptor; size?: "sm" | "md"; className?: string }) {
  if (item.candidate_type === "chunk" && item.source_kind) {
    return <SourceKindIcon kind={item.source_kind} chip size={size} className={className} />;
  }
  const { icon, tone } = iconFor(item);
  const label = itemTypeLabel(item);
  return (
    <span className={cn("inline-flex", className)} role="img" aria-label={label} title={label}>
      <span
        className={cn(
          "flex shrink-0 items-center justify-center rounded-md ring-1 ring-inset",
          size === "sm" ? "size-6" : "size-7",
          toneClasses(tone).soft,
        )}
      >
        <EnumIcon name={icon} className={size === "sm" ? "size-3.5" : "size-4"} />
      </span>
    </span>
  );
}
