"use client";

import * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

import { cn } from "@/lib/utils";

export const TooltipProvider = TooltipPrimitive.Provider;
export const Tooltip = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 6, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        "z-50 max-w-xs rounded-md bg-slate-900 px-2.5 py-1.5 text-xs leading-snug text-slate-50 shadow-md dark:bg-slate-100 dark:text-slate-900",
        "data-[state=delayed-open]:animate-pop-in data-[state=instant-open]:animate-pop-in",
        className,
      )}
      {...props}
    />
  </TooltipPrimitive.Portal>
));
TooltipContent.displayName = "TooltipContent";

export interface SimpleTooltipProps {
  content: React.ReactNode;
  children: React.ReactElement;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  delayDuration?: number;
  /** Render nothing but the child when false/empty. */
  disabled?: boolean;
  className?: string;
}

/** One-liner tooltip: <SimpleTooltip content="…"><button/></SimpleTooltip>. */
export function SimpleTooltip({
  content,
  children,
  side = "top",
  align = "center",
  delayDuration,
  disabled,
  className,
}: SimpleTooltipProps) {
  if (disabled || content === null || content === undefined || content === "") return children;
  return (
    <Tooltip delayDuration={delayDuration}>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side} align={align} className={className}>
        {content}
      </TooltipContent>
    </Tooltip>
  );
}
