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
    soft: "bg-slate-100 text-slate-700 ring-slate-500/15 dark:bg-slate-400/10 dark:text-slate-300 dark:ring-slate-400/20",
    outline: "text-slate-700 ring-slate-300 dark:text-slate-300 dark:ring-slate-600",
    solid: "bg-slate-700 text-white ring-transparent dark:bg-slate-300 dark:text-slate-900",
    dot: "bg-slate-400 dark:bg-slate-500",
    text: "text-slate-600 dark:text-slate-400",
    bar: "bg-slate-500 dark:bg-slate-400",
    track: "bg-slate-200/70 dark:bg-slate-700/50",
    callout: "border-slate-200 bg-slate-50 text-slate-800 dark:border-slate-700/60 dark:bg-slate-800/40 dark:text-slate-200",
  },
  teal: {
    soft: "bg-teal-50 text-teal-800 ring-teal-600/20 dark:bg-teal-400/10 dark:text-teal-300 dark:ring-teal-400/25",
    outline: "text-teal-700 ring-teal-600/40 dark:text-teal-300 dark:ring-teal-400/40",
    solid: "bg-teal-700 text-white ring-transparent dark:bg-teal-400 dark:text-teal-950",
    dot: "bg-teal-500 dark:bg-teal-400",
    text: "text-teal-700 dark:text-teal-300",
    bar: "bg-teal-600 dark:bg-teal-400",
    track: "bg-teal-100 dark:bg-teal-400/15",
    callout: "border-teal-200 bg-teal-50 text-teal-900 dark:border-teal-400/25 dark:bg-teal-400/10 dark:text-teal-100",
  },
  green: {
    soft: "bg-emerald-50 text-emerald-800 ring-emerald-600/20 dark:bg-emerald-400/10 dark:text-emerald-300 dark:ring-emerald-400/25",
    outline: "text-emerald-700 ring-emerald-600/40 dark:text-emerald-300 dark:ring-emerald-400/40",
    solid: "bg-emerald-700 text-white ring-transparent dark:bg-emerald-400 dark:text-emerald-950",
    dot: "bg-emerald-500 dark:bg-emerald-400",
    text: "text-emerald-700 dark:text-emerald-300",
    bar: "bg-emerald-600 dark:bg-emerald-400",
    track: "bg-emerald-100 dark:bg-emerald-400/15",
    callout:
      "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-400/25 dark:bg-emerald-400/10 dark:text-emerald-100",
  },
  amber: {
    soft: "bg-amber-50 text-amber-800 ring-amber-600/25 dark:bg-amber-400/10 dark:text-amber-300 dark:ring-amber-400/25",
    outline: "text-amber-700 ring-amber-600/40 dark:text-amber-300 dark:ring-amber-400/40",
    solid: "bg-amber-500 text-amber-950 ring-transparent dark:bg-amber-400 dark:text-amber-950",
    dot: "bg-amber-500 dark:bg-amber-400",
    text: "text-amber-700 dark:text-amber-300",
    bar: "bg-amber-500 dark:bg-amber-400",
    track: "bg-amber-100 dark:bg-amber-400/15",
    callout: "border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-400/30 dark:bg-amber-400/10 dark:text-amber-100",
  },
  red: {
    soft: "bg-red-50 text-red-800 ring-red-600/20 dark:bg-red-400/10 dark:text-red-300 dark:ring-red-400/25",
    outline: "text-red-700 ring-red-600/40 dark:text-red-300 dark:ring-red-400/40",
    solid: "bg-red-700 text-white ring-transparent dark:bg-red-500 dark:text-white",
    dot: "bg-red-500 dark:bg-red-400",
    text: "text-red-700 dark:text-red-300",
    bar: "bg-red-600 dark:bg-red-400",
    track: "bg-red-100 dark:bg-red-400/15",
    callout: "border-red-300 bg-red-50 text-red-950 dark:border-red-400/30 dark:bg-red-400/10 dark:text-red-100",
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

export function toneClasses(tone: Tone | undefined): ToneClasses {
  return TONE_CLASSES[tone ?? "neutral"];
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
