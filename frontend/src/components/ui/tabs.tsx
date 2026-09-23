"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";

import { cn } from "@/lib/utils";

export const Tabs = TabsPrimitive.Root;

export interface TabsListProps extends React.ComponentPropsWithoutRef<typeof TabsPrimitive.List> {
  /** "underline" (page-level navigation) or "pills" (compact, in cards). */
  variant?: "underline" | "pills";
}

const TabsVariantContext = React.createContext<"underline" | "pills">("underline");

export const TabsList = React.forwardRef<React.ElementRef<typeof TabsPrimitive.List>, TabsListProps>(
  ({ className, variant = "underline", ...props }, ref) => (
    <TabsVariantContext.Provider value={variant}>
      <TabsPrimitive.List
        ref={ref}
        className={cn(
          "flex max-w-full items-center overflow-x-auto",
          variant === "underline" ? "gap-4 border-b border-border" : "inline-flex gap-1 rounded-lg bg-muted p-1",
          className,
        )}
        {...props}
      />
    </TabsVariantContext.Provider>
  ),
);
TabsList.displayName = "TabsList";

export interface TabsTriggerProps extends React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger> {
  /** Small counter badge after the label. */
  count?: number;
}

export const TabsTrigger = React.forwardRef<React.ElementRef<typeof TabsPrimitive.Trigger>, TabsTriggerProps>(
  ({ className, count, children, ...props }, ref) => {
    const variant = React.useContext(TabsVariantContext);
    return (
      <TabsPrimitive.Trigger
        ref={ref}
        className={cn(
          "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap text-[13px] font-medium text-muted-foreground transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
          "[&_svg]:size-4",
          variant === "underline"
            ? "-mb-px h-10 border-b-2 border-transparent px-0.5 hover:text-foreground data-[state=active]:border-primary data-[state=active]:text-foreground"
            : "h-7 rounded-md px-2.5 hover:text-foreground data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm",
          className,
        )}
        {...props}
      >
        {children}
        {typeof count === "number" ? (
          <span className="rounded bg-muted px-1.5 py-px text-[11px] tabular-nums text-muted-foreground">{count}</span>
        ) : null}
      </TabsPrimitive.Trigger>
    );
  },
);
TabsTrigger.displayName = "TabsTrigger";

export const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn("mt-4 focus-visible:outline-none data-[state=active]:animate-fade-in", className)}
    {...props}
  />
));
TabsContent.displayName = "TabsContent";
