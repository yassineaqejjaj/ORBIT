"use client";

import Link from "next/link";
import { ArrowRight, PlugZap } from "lucide-react";

import { ConnectorTypeIcon } from "@/components/connectors/run-stats";
import { CONNECTOR_TYPE_ORDER, CONNECTOR_TYPES } from "@/components/connectors/connector-meta";
import { projectHref } from "@/components/layout/nav";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** Empty-project call to action (docs/FEATURES.md F5): opens the connector onboarding wizard. */
export function ConnectSourcesCta({ slug, isOwner, className }: { slug: string; isOwner: boolean; className?: string }) {
  const base = projectHref(slug, "connectors");
  return (
    <Card className={cn("grid gap-4 border-dashed p-5 sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:items-center", className)}>
      <span className="flex size-11 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <PlugZap className="size-5" aria-hidden />
      </span>
      <div className="grid gap-1">
        <h2 className="text-base font-semibold">Connectez vos 2 premières sources</h2>
        <p className="text-sm text-muted-foreground">
          {isOwner
            ? "SharePoint, Confluence ou Jira : l'assistant teste vos identifiants, vous choisissez le périmètre et ORBIT assemble votre premier contexte en quelques minutes."
            : "Ce projet ne contient encore aucun document. Un propriétaire peut connecter SharePoint, Confluence ou Jira depuis la page Connecteurs."}
        </p>
        {isOwner ? (
          <div className="mt-1 flex flex-wrap gap-1.5">
            {CONNECTOR_TYPE_ORDER.map((type) => (
              <Button key={type} size="xs" variant="subtle" asChild>
                <Link href={`${base}?wizard=${type}`}>
                  <ConnectorTypeIcon type={type} />
                  {CONNECTOR_TYPES[type].label}
                </Link>
              </Button>
            ))}
          </div>
        ) : null}
      </div>
      <Button asChild size="sm">
        <Link href={isOwner ? `${base}?wizard=1` : base}>
          {isOwner ? "Démarrer l'assistant" : "Voir les connecteurs"}
          <ArrowRight aria-hidden />
        </Link>
      </Button>
    </Card>
  );
}
