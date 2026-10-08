import {
  CircleCheck,
  CircleDashed,
  CircleHelp,
  Layers,
  ListTree,
  UserCog,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { ContextPackage, ContextSufficiency } from "@/lib/api/types";
import { AGENT_KIND_META, type AgentKind } from "@/lib/enums";
import { formatNumber } from "@/lib/format";

const VERDICT_META: Record<
  ContextSufficiency["verdict"],
  {
    label: string;
    tone: "green" | "amber" | "red";
    icon: React.ReactNode;
    hint: string;
  }
> = {
  sufficient: {
    label: "Contexte suffisant",
    tone: "green",
    icon: <CircleCheck aria-hidden />,
    hint: "Les sous-sujets de la tâche sont couverts par les éléments servis.",
  },
  partial: {
    label: "Contexte partiel",
    tone: "amber",
    icon: <CircleDashed aria-hidden />,
    hint: "Une partie de la tâche n'est pas couverte : l'agent peut chercher davantage (search_more).",
  },
  insufficient: {
    label: "Contexte insuffisant",
    tone: "red",
    icon: <CircleHelp aria-hidden />,
    hint: "« Demander à ORBIT » répond « Je ne sais pas » plutôt que de deviner.",
  },
};

/** Chantier C signals of a package: sufficiency (§C5), prompt-cache prefix (§C1), profile (§C3), mode (§C2). */
export function AssemblyInsights({ pkg }: { pkg: ContextPackage }) {
  const suff = pkg.sufficiency;
  const meta = suff ? VERDICT_META[suff.verdict] : null;
  const profileKind = pkg.profile?.kind as AgentKind | undefined;
  if (
    !suff &&
    !pkg.cache_prefix_hash &&
    !pkg.profile &&
    pkg.mode !== "progressive"
  )
    return null;
  return (
    <Card>
      <CardContent className="grid gap-4 p-4 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        {suff && meta ? (
          <section
            aria-label="Suffisance du contexte"
            className="grid content-start gap-2"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={meta.tone} icon={meta.icon}>
                {meta.label}
              </Badge>
              <span className="text-xs text-muted-foreground tabular-nums">
                score {formatNumber(suff.score, 2)}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              {meta.hint} {suff.explanation ? `(${suff.explanation}).` : null}
            </p>
            {suff.missing_subtopics.length > 0 ? (
              <div className="grid gap-1">
                <p className="text-[12.5px] font-medium text-foreground">
                  Sous-sujets non couverts
                </p>
                <ul className="flex flex-wrap gap-1.5">
                  {suff.missing_subtopics.map((topic) => (
                    <li key={topic}>
                      <Badge tone="neutral" size="sm">
                        {topic}
                      </Badge>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </section>
        ) : (
          <span />
        )}
        <dl className="grid content-start gap-2 text-xs">
          {pkg.cache_prefix_hash ? (
            <div className="flex items-start gap-2">
              <Layers
                className="mt-0.5 size-3.5 shrink-0 text-primary"
                aria-hidden
              />
              <div className="min-w-0">
                <dt className="font-medium text-foreground">
                  Préfixe stable (cache de prompt)
                </dt>
                <dd className="text-muted-foreground">
                  {formatNumber(pkg.cache_prefix_tokens ?? 0, 0)} tokens ·{" "}
                  <code className="font-mono" title={pkg.cache_prefix_hash}>
                    {pkg.cache_prefix_hash.slice(0, 12)}
                  </code>{" "}
                  ·{" "}
                  {pkg.cache_prefix_reused
                    ? "déjà servi récemment (réutilisable)"
                    : "nouveau préfixe"}
                </dd>
              </div>
            </div>
          ) : null}
          {pkg.profile && profileKind ? (
            <div className="flex items-start gap-2">
              <UserCog
                className="mt-0.5 size-3.5 shrink-0 text-primary"
                aria-hidden
              />
              <div className="min-w-0">
                <dt className="font-medium text-foreground">
                  Profil «{" "}
                  {AGENT_KIND_META[profileKind]?.label ?? pkg.profile.kind} »
                  {pkg.profile.customized ? " (personnalisé)" : ""}
                </dt>
                <dd className="text-muted-foreground">
                  {pkg.profile.sections.length} section(s) servie(s)
                  {pkg.profile.token_budget
                    ? ` · budget ${formatNumber(pkg.profile.token_budget, 0)}`
                    : ""}
                </dd>
              </div>
            </div>
          ) : null}
          {pkg.mode === "progressive" ? (
            <div className="flex items-start gap-2">
              <ListTree
                className="mt-0.5 size-3.5 shrink-0 text-primary"
                aria-hidden
              />
              <div className="min-w-0">
                <dt className="font-medium text-foreground">
                  Contexte progressif
                </dt>
                <dd className="text-muted-foreground">
                  {pkg.index?.length ?? 0} entrée(s) d&apos;index à déplier via
                  expand_source, get_decision ou get_memory_item.
                </dd>
              </div>
            </div>
          ) : null}
        </dl>
      </CardContent>
    </Card>
  );
}
