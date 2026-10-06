/**
 * Tone → Tailwind class tokens (light + dark). Full class strings are listed so Tailwind can detect them.
 * Consumers: Badge, ScoreBar, Progress, StatusDot, callouts…
 */
import type { Tone } from "@/lib/enums";

export interface ToneClasses {
  /** Soft pill: tinted background, strong text, subtle ring. */
  soft: string;
  /** Outline pill. */
  outline: string;
  /** Solid pill. */
  solid: string;
  /** Small status dot / legend swatch background. */
  dot: string;
  /** Foreground text only. */
  text: string;
  /** Filled bar (progress, score). */
  bar: string;
  /** Light track behind a bar. */
  track: string;
  /** Callout container (banner, alert). */
  callout: string;
}

export const TONE_CLASSES: Record<Tone, ToneClasses> = {
  neutral: {
    soft: "bg-surface-3 text-muted-foreground ring-border",
    outline: "text-muted-foreground ring-border-strong",
    solid: "bg-foreground text-background ring-transparent",
    dot: "bg-subtle-foreground",
    text: "text-muted-foreground",
    bar: "bg-subtle-foreground",
    track: "bg-surface-3",
    callout: "border-border bg-surface-2 text-foreground",
  },

  /* Historical name: rendered with the NOVA coral accent (teal is no longer part of the UI). */
  teal: {
    soft: "bg-accent-soft text-accent-text ring-accent-coral/20",
    outline: "text-accent-text ring-accent-coral/40",
    solid: "bg-primary text-primary-foreground ring-transparent",
    dot: "bg-accent-coral",
    text: "text-accent-text",
    bar: "bg-accent-coral",
    track: "bg-accent-soft",
    callout: "border-accent-coral/25 bg-accent-soft text-foreground",
  },

  green: {
    soft: "bg-success/12 text-success ring-success/20",
    outline: "text-success ring-success/40",
    solid: "bg-success text-white ring-transparent dark:text-black",
    dot: "bg-success",
    text: "text-success",
    bar: "bg-success",
    track: "bg-success/15",
    callout: "border-success/25 bg-success/10 text-foreground",
  },

  amber: {
    soft: "bg-warning/12 text-warning ring-warning/25",
    outline: "text-warning ring-warning/40",
    solid: "bg-status-warning text-black ring-transparent",
    dot: "bg-status-warning",
    text: "text-warning",
    bar: "bg-status-warning",
    track: "bg-warning/15",
    callout: "border-warning/30 bg-warning/10 text-foreground",
  },

  red: {
    soft: "bg-danger/12 text-danger ring-danger/20",
    outline: "text-danger ring-danger/40",
    solid: "bg-destructive text-destructive-foreground ring-transparent",
    dot: "bg-danger",
    text: "text-danger",
    bar: "bg-danger",
    track: "bg-danger/15",
    callout: "border-danger/30 bg-danger/10 text-foreground",
  },

  blue: {
    soft: "bg-blue-50 text-blue-800 ring-blue-600/20 dark:bg-blue-400/10 dark:text-blue-300 dark:ring-blue-400/25",
    outline: "text-blue-700 ring-blue-600/40 dark:text-blue-300 dark:ring-blue-400/40",
    solid: "bg-blue-700 text-white ring-transparent dark:bg-blue-400 dark:text-blue-950",
    dot: "bg-blue-500 dark:bg-blue-400",
    text: "text-blue-700 dark:text-blue-300",
    bar: "bg-blue-600 dark:bg-blue-400",
    track: "bg-blue-100 dark:bg-blue-400/15",
    callout: "border-blue-200 bg-blue-50 text-blue-950 dark:border-blue-400/25 dark:bg-blue-400/10 dark:text-blue-100",
  },
  sky: {
    soft: "bg-sky-50 text-sky-800 ring-sky-600/20 dark:bg-sky-400/10 dark:text-sky-300 dark:ring-sky-400/25",
    outline: "text-sky-700 ring-sky-600/40 dark:text-sky-300 dark:ring-sky-400/40",
    solid: "bg-sky-700 text-white ring-transparent dark:bg-sky-400 dark:text-sky-950",
    dot: "bg-sky-500 dark:bg-sky-400",
    text: "text-sky-700 dark:text-sky-300",
    bar: "bg-sky-600 dark:bg-sky-400",
    track: "bg-sky-100 dark:bg-sky-400/15",
    callout: "border-sky-200 bg-sky-50 text-sky-950 dark:border-sky-400/25 dark:bg-sky-400/10 dark:text-sky-100",
  },
  violet: {
    soft: "bg-violet-50 text-violet-800 ring-violet-600/20 dark:bg-violet-400/10 dark:text-violet-300 dark:ring-violet-400/25",
    outline: "text-violet-700 ring-violet-600/40 dark:text-violet-300 dark:ring-violet-400/40",
    solid: "bg-violet-700 text-white ring-transparent dark:bg-violet-400 dark:text-violet-950",
    dot: "bg-violet-500 dark:bg-violet-400",
    text: "text-violet-700 dark:text-violet-300",
    bar: "bg-violet-600 dark:bg-violet-400",
    track: "bg-violet-100 dark:bg-violet-400/15",
    callout:
      "border-violet-200 bg-violet-50 text-violet-950 dark:border-violet-400/25 dark:bg-violet-400/10 dark:text-violet-100",
  },
  orange: {
    soft: "bg-orange-50 text-orange-800 ring-orange-600/20 dark:bg-orange-400/10 dark:text-orange-300 dark:ring-orange-400/25",
    outline: "text-orange-700 ring-orange-600/40 dark:text-orange-300 dark:ring-orange-400/40",
    solid: "bg-orange-600 text-white ring-transparent dark:bg-orange-400 dark:text-orange-950",
    dot: "bg-orange-500 dark:bg-orange-400",
    text: "text-orange-700 dark:text-orange-300",
    bar: "bg-orange-500 dark:bg-orange-400",
    track: "bg-orange-100 dark:bg-orange-400/15",
    callout:
      "border-orange-200 bg-orange-50 text-orange-950 dark:border-orange-400/25 dark:bg-orange-400/10 dark:text-orange-100",
  },
  pink: {
    soft: "bg-pink-50 text-pink-800 ring-pink-600/20 dark:bg-pink-400/10 dark:text-pink-300 dark:ring-pink-400/25",
    outline: "text-pink-700 ring-pink-600/40 dark:text-pink-300 dark:ring-pink-400/40",
    solid: "bg-pink-700 text-white ring-transparent dark:bg-pink-400 dark:text-pink-950",
    dot: "bg-pink-500 dark:bg-pink-400",
    text: "text-pink-700 dark:text-pink-300",
    bar: "bg-pink-600 dark:bg-pink-400",
    track: "bg-pink-100 dark:bg-pink-400/15",
    callout: "border-pink-200 bg-pink-50 text-pink-950 dark:border-pink-400/25 dark:bg-pink-400/10 dark:text-pink-100",
  },
};

/** NOVA tone names, accepted alongside the historical palette names. */
export type NovaTone = "accent" | "success" | "warning" | "danger";
export type AnyTone = Tone | NovaTone;

const NOVA_TONE_ALIASES: Record<NovaTone, Tone> = {
  accent: "teal",
  success: "green",
  warning: "amber",
  danger: "red",
};

export function resolveTone(tone: AnyTone | undefined): Tone {
  if (!tone) return "neutral";
  return tone in NOVA_TONE_ALIASES ? NOVA_TONE_ALIASES[tone as NovaTone] : (tone as Tone);
}

export function toneClasses(tone: AnyTone | undefined): ToneClasses {
  return TONE_CLASSES[resolveTone(tone)];
}

/**
 * Chart series colors (CSS variables, theme-aware), fixed categorical order.
 * Validated with the dataviz palette checker in light and dark.
 */
export const CHART_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--chart-6)",
] as const;

export const CHART_THEME = {
  grid: "var(--chart-grid)",
  axis: "var(--chart-axis)",
  text: "var(--muted-foreground)",
  tooltipBg: "var(--popover)",
  tooltipBorder: "var(--border)",
} as const;
