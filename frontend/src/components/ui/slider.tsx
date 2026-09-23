"use client";

import * as React from "react";
import * as SliderPrimitive from "@radix-ui/react-slider";

import { cn } from "@/lib/utils";

export interface SliderProps extends React.ComponentPropsWithoutRef<typeof SliderPrimitive.Root> {
  /** Accessible labels for each thumb (defaults to the Root aria-label). */
  thumbLabels?: string[];
}

export const Slider = React.forwardRef<React.ElementRef<typeof SliderPrimitive.Root>, SliderProps>(
  ({ className, thumbLabels, ...props }, ref) => {
    const count = (props.value ?? props.defaultValue ?? [0]).length;
    return (
      <SliderPrimitive.Root
        ref={ref}
        className={cn(
          "relative flex w-full touch-none select-none items-center py-1.5 data-[disabled]:opacity-50",
          className,
        )}
        {...props}
      >
        <SliderPrimitive.Track className="relative h-1.5 w-full grow overflow-hidden rounded-full bg-muted">
          <SliderPrimitive.Range className="absolute h-full rounded-full bg-primary" />
        </SliderPrimitive.Track>
        {Array.from({ length: count }, (_, i) => (
          <SliderPrimitive.Thumb
            key={i}
            aria-label={thumbLabels?.[i] ?? props["aria-label"]}
            className={cn(
              "block size-4 rounded-full border-2 border-primary bg-background shadow-sm transition-[box-shadow]",
              "hover:ring-4 hover:ring-ring/15 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring/25",
              "disabled:pointer-events-none",
            )}
          />
        ))}
      </SliderPrimitive.Root>
    );
  },
);
Slider.displayName = "Slider";
