"use client";

import * as React from "react";

import { useTheme } from "@/components/providers/theme-provider";
import type { Tone } from "@/lib/enums";

/**
 * SVG fill colours for semantic tones (same steps as the Tailwind `bar` tone classes in lib/tones.ts:
 * 600 on light surfaces, 400 on dark), so chart marks match badges and HTML bars in both themes.
 */
const TONE_FILLS: Record<Tone, { light: string; dark: string }> = {
  neutral: { light: "#64748b", dark: "#94a3b8" },
  teal: { light: "#e8344b", dark: "#f8485e" } /* coral accent */,
  green: { light: "#059669", dark: "#34d399" },
  amber: { light: "#f59e0b", dark: "#fbbf24" },
  red: { light: "#dc2626", dark: "#f87171" },
  blue: { light: "#2563eb", dark: "#60a5fa" },
  sky: { light: "#0284c7", dark: "#38bdf8" },
  violet: { light: "#7c3aed", dark: "#a78bfa" },
  orange: { light: "#f97316", dark: "#fb923c" },
  pink: { light: "#db2777", dark: "#f472b6" },
};

/** Neutral fill for folded "Autres" categories. */
export const OTHER_FILL = "var(--chart-axis)";

/** Returns a resolver `tone → hex` for the current theme. */
export function useToneFill(): (tone: Tone) => string {
  const { resolvedTheme } = useTheme();
  return React.useCallback((tone: Tone) => TONE_FILLS[tone][resolvedTheme], [resolvedTheme]);
}
