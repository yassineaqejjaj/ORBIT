"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { RefreshCw, ServerCrash } from "lucide-react";

import { OrbitLogo } from "@/components/brand/orbit-logo";
import { AppHeader } from "@/components/layout/app-header";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { CommandPalette } from "@/components/layout/command-palette";
import { MobileNav } from "@/components/layout/mobile-nav";
import { MobileTabBar } from "@/components/layout/mobile-tab-bar";
import { ShellProvider, useShell } from "@/components/layout/shell-context";
import { SplashScreen } from "@/components/layout/splash-screen";
import { CreateProjectDialog } from "@/components/projects/create-project-dialog";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

function GlobalCreateProjectDialog() {
  const { createProjectOpen, setCreateProjectOpen } = useShell();
  return <CreateProjectDialog open={createProjectOpen} onOpenChange={setCreateProjectOpen} />;
}

function BackendUnavailable({ error, onRetry, retrying }: { error: unknown; onRetry: () => void; retrying: boolean }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-background px-4 text-center">
      <OrbitLogo />
      <div className="grid max-w-md justify-items-center gap-3">
        <span className="flex size-11 items-center justify-center rounded-xl border border-border bg-card text-destructive shadow-panel">
          <ServerCrash className="size-5" aria-hidden />
        </span>
        <h1 className="text-lg font-semibold tracking-tight">Service ORBIT indisponible</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">{errorMessage(error)}</p>
        <Button onClick={onRetry} loading={retrying} leftIcon={<RefreshCw aria-hidden />}>
          Réessayer
        </Button>
      </div>
    </div>
  );
}

/** Authenticated application shell: auth guard, sidebar, header, command palette. */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const me = useMe();
  const params = useParams<{ slug?: string }>();
  const slug = typeof params.slug === "string" ? params.slug : undefined;

  if (me.isPending) return <SplashScreen />;
  if (me.isError) {
    if (me.error.isUnauthorized) return <SplashScreen label="Redirection vers la connexion…" />;
    return <BackendUnavailable error={me.error} onRetry={() => void me.refetch()} retrying={me.isFetching} />;
  }

  return (
    <ShellProvider>
      <a
        href="#main-content"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Aller au contenu
      </a>
      <div className="flex min-h-dvh bg-background">
        <AppSidebar slug={slug} />
        <MobileNav slug={slug} />
        <div className="flex min-w-0 flex-1 flex-col">
          <AppHeader />
          <main
            id="main-content"
            tabIndex={-1}
            className={cn(
              "flex-1 focus:outline-none",
              // Keep content clear of the fixed mobile tab bar (64 px + safe area).
              slug && "pb-[calc(4rem+env(safe-area-inset-bottom))] lg:pb-0",
            )}
          >
            <div className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</div>
          </main>
        </div>
      </div>
      <MobileTabBar slug={slug} />
      <CommandPalette />
      <GlobalCreateProjectDialog />
    </ShellProvider>
  );
}
