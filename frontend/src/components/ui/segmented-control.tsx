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
}

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
        "inline-flex items-center gap-0.5 rounded-lg border border-border bg-muted p-0.5",
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
            "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium text-muted-foreground transition-[color,background-color,box-shadow]",
            "hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
            "data-[state=on]:bg-background data-[state=on]:text-foreground data-[state=on]:shadow-sm",
            size === "sm" ? "h-6 px-2 text-xs [&_svg]:size-3.5" : "h-7 px-2.5 text-[13px] [&_svg]:size-4",
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
