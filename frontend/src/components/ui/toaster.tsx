"use client";

import { Toaster as SonnerToaster } from "sonner";

import { useTheme } from "@/components/providers/theme-provider";

/** Global toast outlet (sonner). Use `toast.success(...)`, `toast.error(...)` from "sonner". */
export function Toaster() {
  const { resolvedTheme } = useTheme();
  return (
    <SonnerToaster
      theme={resolvedTheme}
      position="bottom-right"
      mobileOffset={{ bottom: "calc(5rem + env(safe-area-inset-bottom))" }}
      closeButton
      richColors
      duration={4500}
      visibleToasts={4}
      toastOptions={{
        classNames: {
          toast: "!rounded-menu !border !border-border !shadow-lg !font-sans !text-[13px]",
          title: "!font-medium",
          description: "!text-muted-foreground",
          closeButton: "!bg-popover !border-border",
        },
      }}
      containerAriaLabel="Notifications"
    />
  );
}
