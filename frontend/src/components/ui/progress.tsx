"use client";

import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";

import type { Tone } from "@/lib/enums";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

export interface ProgressProps extends Omit<React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root>, "value"> {
  /** 0..100 — omit (or null) for an indeterminate bar. */
  value?: number | null;
  tone?: Tone;
  size?: "xs" | "sm" | "md";
}

const heights = { xs: "h-1", sm: "h-1.5", md: "h-2" } as const;

export const Progress = React.forwardRef<React.ElementRef<typeof ProgressPrimitive.Root>, ProgressProps>(
  ({ className, value, tone = "teal", size = "sm", ...props }, ref) => {
    const t = toneClasses(tone);
    const indeterminate = value === null || value === undefined;
    const clamped = indeterminate ? 0 : Math.max(0, Math.min(100, value));
    return (
      <ProgressPrimitive.Root
        ref={ref}
        value={indeterminate ? null : clamped}
        className={cn("relative w-full overflow-hidden rounded-full", heights[size], t.track, className)}
        {...props}
      >
        <ProgressPrimitive.Indicator
          className={cn(
            "h-full rounded-full transition-[width] duration-500 ease-out",
            t.bar,
            indeterminate && "w-1/3 animate-indeterminate",
          )}
          style={indeterminate ? undefined : { width: `${clamped}%` }}
        />
      </ProgressPrimitive.Root>
    );
  },
);
Progress.displayName = "Progress";
