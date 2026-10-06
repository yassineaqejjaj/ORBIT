"use client";

import * as React from "react";
import { Menu, Search } from "lucide-react";

import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { useShell } from "@/components/layout/shell-context";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { UserMenu } from "@/components/layout/user-menu";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { modKeyLabel } from "@/lib/utils";

/** Sticky top bar: mobile menu, breadcrumb, search trigger (⌘K), theme toggle, user menu. */
export function AppHeader() {
  const { openCommandPalette, setMobileNavOpen } = useShell();
  const [mod, setMod] = React.useState("⌘");
  React.useEffect(() => setMod(modKeyLabel()), []);

  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b border-border bg-background/85 px-3 backdrop-blur-md supports-[backdrop-filter]:bg-background/70 sm:px-4 lg:px-6">
      <Button
        variant="ghost"
        size="icon-sm"
        className="lg:hidden"
        onClick={() => setMobileNavOpen(true)}
        aria-label="Ouvrir la navigation"
      >
        <Menu aria-hidden />
      </Button>

      <Breadcrumbs className="flex-1" />

      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={openCommandPalette}
          className="hidden h-8 w-64 items-center gap-2 rounded-full border border-border bg-surface-2/80 pl-3 pr-1.5 text-[13px] text-subtle-foreground transition-colors duration-150 hover:border-border-strong hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 md:flex xl:w-72"
          aria-label="Rechercher (raccourci ⌘K ou Ctrl+K)"
          aria-keyshortcuts="Meta+K Control+K"
        >
          <Search className="size-3.5" aria-hidden />
          <span className="flex-1 text-left">Rechercher</span>
          <span className="flex items-center gap-0.5" aria-hidden>
            <Kbd className="rounded-full px-1.5">{mod === "⌘" ? "⌘K" : `${mod}+K`}</Kbd>
          </span>
        </button>
        <Button
          variant="ghost"
          size="icon-sm"
          className="md:hidden"
          onClick={openCommandPalette}
          aria-label="Rechercher"
        >
          <Search aria-hidden />
        </Button>
        <ThemeToggle />
        {/* ≥ lg the account menu sits at the bottom of the sidebar. */}
        <div className="lg:hidden">
          <UserMenu />
        </div>
      </div>
    </header>
  );
}
