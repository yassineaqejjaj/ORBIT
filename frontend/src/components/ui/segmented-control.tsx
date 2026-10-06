"use client";

import * as React from "react";
import * as ToggleGroupPrimitive from "@radix-ui/react-toggle-group";

import { cn } from "@/lib/utils";

export interface SegmentedOption<V extends string = string> {
  value: V;
  label: React.ReactNode;
  icon?: React.ReactNode;
  disabled?: boolean;
  /** Accessible label when `label` is icon-only. */
  ariaLabel?: string;
  /** NOVA: the active pill takes this status tint (e.g. Always / Ask / Never). */
  tone?: "accent" | "success" | "warning" | "danger";
}

const ACTIVE_TONE: Record<NonNullable<SegmentedOption["tone"]>, string> = {
  accent: "data-[state=on]:bg-accent-soft data-[state=on]:text-accent-text",
  success: "data-[state=on]:bg-success/15 data-[state=on]:text-success",
  warning: "data-[state=on]:bg-warning/15 data-[state=on]:text-warning",
  danger: "data-[state=on]:bg-danger/15 data-[state=on]:text-danger",
};

export interface SegmentedControlProps<V extends string = string> {
  value: V;
  onValueChange: (value: V) => void;
  options: ReadonlyArray<SegmentedOption<V>>;
  size?: "sm" | "md";
  className?: string;
  /** Stretch segments to fill the width. */
  fullWidth?: boolean;
  "aria-label"?: string;
}

/** Single-choice segmented control (Radix ToggleGroup, arrow-key navigable). */
export function SegmentedControl<V extends string = string>({
  value,
  onValueChange,
  options,
  size = "md",
  className,
  fullWidth,
  "aria-label": ariaLabel,
}: SegmentedControlProps<V>) {
  return (
    <ToggleGroupPrimitive.Root
      type="single"
      value={value}
      onValueChange={(v) => {
        if (v) onValueChange(v as V); // prevent deselection
      }}
      aria-label={ariaLabel}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-full border border-border bg-surface-2 p-0.5",
        fullWidth && "flex w-full",
        className,
      )}
    >
      {options.map((o) => (
        <ToggleGroupPrimitive.Item
          key={o.value}
          value={o.value}
          disabled={o.disabled}
          aria-label={o.ariaLabel}
          className={cn(
            "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-full font-medium text-muted-foreground transition-[color,background-color,box-shadow] duration-150",
            "hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50",
            o.tone
              ? ACTIVE_TONE[o.tone]
              : "data-[state=on]:bg-surface data-[state=on]:text-foreground data-[state=on]:shadow-xs dark:data-[state=on]:bg-surface-3",
            size === "sm" ? "h-6 px-2.5 text-xs [&_svg]:size-3.5" : "h-7 px-3 text-[13px] [&_svg]:size-4",
            fullWidth && "flex-1",
          )}
        >
          {o.icon}
          {o.label}
        </ToggleGroupPrimitive.Item>
      ))}
    </ToggleGroupPrimitive.Root>
  );
}
