import { EnumIcon } from "@/components/domain/enum-icon";
import { getMeta, SOURCE_KIND_META, type SourceKind } from "@/lib/enums";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

export interface SourceKindIconProps {
  kind: SourceKind | string | null | undefined;
  /** Render the icon inside a tinted square chip. */
  chip?: boolean;
  /** Append the French label. */
  withLabel?: boolean;
  size?: "sm" | "md";
  className?: string;
}

/** Lucide icon for a SourceKind (document, note, ticket, crm, feedback, agent_trace, url). */
export function SourceKindIcon({ kind, chip = false, withLabel = false, size = "md", className }: SourceKindIconProps) {
  const meta = kind && kind in SOURCE_KIND_META ? SOURCE_KIND_META[kind as SourceKind] : null;
  const fallback = getMeta(SOURCE_KIND_META, kind);
  const iconSize = size === "sm" ? "size-3.5" : "size-4";
  const icon = <EnumIcon name={meta?.icon ?? "FileText"} className={iconSize} />;

  const iconNode = chip ? (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-md ring-1 ring-inset",
        size === "sm" ? "size-6" : "size-7",
        toneClasses(meta?.tone).soft,
      )}
    >
      {icon}
    </span>
  ) : (
    <span className={cn("flex shrink-0", toneClasses(meta?.tone).text)}>{icon}</span>
  );

  if (!withLabel) {
    return (
      <span className={cn("inline-flex", className)} role="img" aria-label={fallback.label} title={fallback.label}>
        {iconNode}
      </span>
    );
  }
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1.5 text-[13px]", className)}>
      {iconNode}
      <span className="truncate">{fallback.label}</span>
    </span>
  );
}
