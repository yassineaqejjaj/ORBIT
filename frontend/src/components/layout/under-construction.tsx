import * as React from "react";
import { Construction } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";

export interface UnderConstructionProps {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  /** Planned capabilities listed in the empty state. */
  upcoming?: string[];
}

/** Temporary page body for routes being implemented (PageHeader + EmptyState). */
export function UnderConstruction({ title, description, icon, upcoming }: UnderConstructionProps) {
  return (
    <>
      <PageHeader
        title={title}
        description={description}
        icon={icon}
        meta={
          <Badge tone="amber" dot>
            Bientôt disponible
          </Badge>
        }
      />
      <EmptyState
        size="lg"
        icon={<Construction />}
        title="Page en cours de construction"
        description="Cette vue est en cours de finalisation par l'équipe ORBIT. Les données du projet restent accessibles via l'API et le serveur MCP."
      >
        {upcoming?.length ? (
          <ul className="mt-2 grid max-w-md gap-1.5 text-left text-[13px] text-muted-foreground">
            {upcoming.map((item) => (
              <li key={item} className="flex items-start gap-2">
                <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-brand" aria-hidden />
                {item}
              </li>
            ))}
          </ul>
        ) : null}
      </EmptyState>
    </>
  );
}
