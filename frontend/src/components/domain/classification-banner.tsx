import { ShieldAlert } from "lucide-react";

import { CLASSIFICATION_META, toClassification, type Classification } from "@/lib/enums";
import { cn } from "@/lib/utils";

export type ClassificationBannerContext = "display" | "ingest" | "serve" | "project";

export interface ClassificationBannerProps {
  /** Highest classification level of the content on screen (or pass `levels`). */
  level?: number | null;
  /** Several levels: the banner uses the maximum. */
  levels?: ReadonlyArray<number | null | undefined>;
  /** What is happening with the content (adapts the message). */
  context?: ClassificationBannerContext;
  /** Extra sentence appended to the message. */
  message?: string;
  /** Slimmer single-line variant (tables, sheets). */
  compact?: boolean;
  className?: string;
}

const CONTEXT_TEXT: Record<ClassificationBannerContext, string> = {
  display: "vous consultez des informations à diffusion restreinte",
  ingest: "ces informations seront ingérées avec une diffusion restreinte",
  serve: "ce contexte servi aux agents contient des informations à diffusion restreinte",
  project: "ce projet contient des informations à diffusion restreinte",
};

const LEVEL_TEXT: Record<2 | 3, string> = {
  2: "réservé aux personnes habilitées C2 ou plus. Ne le partagez pas hors du périmètre autorisé.",
  3: "accès strictement nominatif, toute consultation est journalisée. Aucune copie ni diffusion.",
};

/** Maximum classification of a list of levels. */
export function maxClassification(levels: ReadonlyArray<number | null | undefined>): Classification {
  return levels.reduce<Classification>((max, l) => {
    const c = toClassification(l);
    return c > max ? c : max;
  }, 0);
}

/**
 * Warning banner shown whenever C2/C3 content is displayed, ingested or served (ARCHITECTURE §3).
 * Renders nothing below C2.
 */
export function ClassificationBanner({
  level,
  levels,
  context = "display",
  message,
  compact = false,
  className,
}: ClassificationBannerProps) {
  const lvl = levels ? maxClassification([...levels, level]) : toClassification(level);
  if (lvl < 2) return null;
  const meta = CLASSIFICATION_META[lvl];
  const secret = lvl === 3;

  return (
    <div
      role="alert"
      aria-live="polite"
      className={cn(
        "flex items-start gap-3 rounded-lg border text-[13px]",
        compact ? "px-3 py-2" : "px-4 py-3",
        secret
          ? "border-danger/30 bg-danger/10 text-foreground"
          : "border-warning/30 bg-warning/10 text-foreground",
        className,
      )}
    >
      <span
        className={cn(
          "mt-px flex shrink-0 items-center justify-center rounded-md",
          compact ? "size-5" : "size-6",
          secret ? "bg-destructive text-destructive-foreground" : "bg-status-warning text-black",
        )}
        aria-hidden
      >
        <ShieldAlert className={compact ? "size-3" : "size-3.5"} />
      </span>
      <p className="min-w-0 leading-relaxed">
        <strong className="font-semibold">
          Contenu classifié {meta.code} — {meta.label}
        </strong>
        {"\u00a0"}: {CONTEXT_TEXT[context]} ; {LEVEL_TEXT[lvl as 2 | 3]}
        {message ? <> {message}</> : null}
      </p>
    </div>
  );
}
