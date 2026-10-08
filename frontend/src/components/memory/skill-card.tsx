"use client";

import { ClipboardCheck, Download } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { skillDownloadUrl } from "@/lib/api/endpoints";
import type { MemoryItem } from "@/lib/api/types";
import { AGENT_KIND_META, INTENT_META } from "@/lib/enums";

/** §D1 a procedure served as an Agent Skill: name, scope of application and SKILL.md download. */
export function SkillCard({ slug, item }: { slug: string; item: MemoryItem }) {
  const meta = item.skill_meta;
  if (item.kind !== "procedure" || !meta) return null;
  const active = item.is_current && (item.status === "validated" || item.status === "proposed");
  return (
    <section aria-label="Skill" className="space-y-3 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <ClipboardCheck className="size-4 text-muted-foreground" aria-hidden />
        <h3 className="text-[13px] font-semibold">Skill</h3>
        <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{meta.name}</code>
        {active ? (
          <a
            href={skillDownloadUrl(slug, meta.name)}
            download
            className="ml-auto inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
          >
            <Download className="size-3.5" aria-hidden />
            Télécharger SKILL.md (zip)
          </a>
        ) : null}
      </div>
      {meta.description ? <p className="text-[13px] text-muted-foreground">{meta.description}</p> : null}
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <span className="text-muted-foreground">Tâches :</span>
        {meta.task_types.length ? (
          meta.task_types.map((t) => (
            <Badge key={t} tone="sky" size="sm">
              {INTENT_META[t]?.label ?? t}
            </Badge>
          ))
        ) : (
          <span>toutes</span>
        )}
        <span className="ml-2 text-muted-foreground">Agents :</span>
        {meta.agent_kinds.length ? (
          meta.agent_kinds.map((k) => (
            <Badge key={k} tone="violet" size="sm">
              {AGENT_KIND_META[k]?.label ?? k}
            </Badge>
          ))
        ) : (
          <span>tous</span>
        )}
      </div>
    </section>
  );
}
