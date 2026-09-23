"use client";

import * as React from "react";
import { usePathname } from "next/navigation";

import { SidebarContent } from "@/components/layout/app-sidebar";
import { useShell } from "@/components/layout/shell-context";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";

/** Sidebar as a left sheet below the lg breakpoint. */
export function MobileNav({ slug }: { slug?: string }) {
  const { mobileNavOpen, setMobileNavOpen } = useShell();
  const pathname = usePathname();

  React.useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname, setMobileNavOpen]);

  return (
    <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
      <SheetContent side="left" size="sm" className="bg-sidebar p-0 lg:hidden">
        <SheetTitle className="sr-only">Navigation</SheetTitle>
        <SheetDescription className="sr-only">Navigation principale d&apos;ORBIT</SheetDescription>
        <SidebarContent slug={slug} onNavigate={() => setMobileNavOpen(false)} />
      </SheetContent>
    </Sheet>
  );
}
