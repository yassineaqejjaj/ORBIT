"use client";

import * as React from "react";
import Link from "next/link";
import { Download, FileCheck2, Printer, ShieldCheck } from "lucide-react";

import { projectHref } from "@/components/layout/nav";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { useCurrentProject } from "@/hooks/use-current-project";
import { complianceReportUrl, type ComplianceReportParams } from "@/lib/api/endpoints";
import { cn } from "@/lib/utils";

type Scope = "period" | "request" | "decision";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const SAFEGUARDS: ReadonlyArray<{ title: string; text: string }> = [
  {
    title: "Détection d'injection de prompt",
    text: "Chaque extrait est analysé à l'ingestion (règles FR/EN, liens d'exfiltration, texte caché). Au-dessus du seuil, il est mis en quarantaine et n'est jamais servi.",
  },
  {
    title: "Spotlighting",
    text: "Tout contenu servi aux agents (contexte, MCP, Demander à ORBIT) est balisé comme donnée non fiable, avec une consigne d'en-tête.",
  },
  {
    title: "Confiance par source",
    text: "Les sources de confiance faible (pages web, retours, traces d'agents) sont pénalisées au classement et jamais promues automatiquement en mémoire validée.",
  },
  {
    title: "Alerte d'empoisonnement",
    text: "Une rafale de propositions venant d'une seule source récente ou d'un agent déclenche une alerte dans « À traiter ».",
  },
];

function toIso(date: string, endOfDay: boolean): string | undefined {
  if (!date) return undefined;
  return `${date}T${endOfDay ? "23:59:59" : "00:00:00"}Z`;
}

/** Paramètres → Conformité IA: safeguards in force and AI Act traceability report export (owners). */
export function CompliancePanel() {
  const { slug, isOwner } = useCurrentProject();
  const [scope, setScope] = React.useState<Scope>("period");
  const [from, setFrom] = React.useState("");
  const [to, setTo] = React.useState("");
  const [requestId, setRequestId] = React.useState("");
  const [memoryId, setMemoryId] = React.useState("");

  const params: ComplianceReportParams =
    scope === "period"
      ? { from: toIso(from, false), to: toIso(to, true) }
      : scope === "request"
        ? { request_id: requestId.trim() }
        : { memory_id: memoryId.trim() };
  const idValue = scope === "request" ? requestId.trim() : scope === "decision" ? memoryId.trim() : "";
  const idError = scope !== "period" && idValue !== "" && !UUID_RE.test(idValue) ? "Identifiant (UUID) invalide." : undefined;
  const rangeError = scope === "period" && from && to && from > to ? "La date de début doit précéder la date de fin." : undefined;
  const ready = !idError && !rangeError && (scope === "period" || UUID_RE.test(idValue));

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="size-4" aria-hidden />
            Garde-fous de sécurité IA
          </CardTitle>
          <CardDescription>Actifs sur toute l&apos;instance ; seuils réglés par l&apos;administrateur (variables ORBIT_…).</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="grid gap-3">
            {SAFEGUARDS.map((item) => (
              <li key={item.title} className="grid gap-0.5">
                <p className="text-[13px] font-medium text-foreground">{item.title}</p>
                <p className="text-xs leading-snug text-muted-foreground">{item.text}</p>
              </li>
            ))}
          </ul>
          {isOwner ? (
            <Button asChild variant="outline" size="sm" className="mt-4">
              <Link href={`${projectHref(slug, "sources")}?tab=quarantine`}>Examiner la quarantaine</Link>
            </Button>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileCheck2 className="size-4" aria-hidden />
            Rapport de traçabilité (AI Act)
          </CardTitle>
          <CardDescription>
            Quel contexte, quelles sources, quelle décision de gouvernance, quel modèle — par période, par requête ou par décision.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {!isOwner ? (
            <Alert tone="blue">L&apos;export du rapport est réservé aux propriétaires du projet.</Alert>
          ) : (
            <>
              <SegmentedControl<Scope>
                aria-label="Périmètre du rapport"
                value={scope}
                onValueChange={setScope}
                options={[
                  { value: "period", label: "Période" },
                  { value: "request", label: "Requête" },
                  { value: "decision", label: "Décision" },
                ]}
              />
              {scope === "period" ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field id="compliance-from" label="Du" error={rangeError}>
                    <Input id="compliance-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
                  </Field>
                  <Field id="compliance-to" label="Au">
                    <Input id="compliance-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
                  </Field>
                </div>
              ) : (
                <Field
                  id="compliance-id"
                  label={scope === "request" ? "Identifiant de la requête de contexte" : "Identifiant de la décision (item mémoire)"}
                  hint={
                    scope === "request"
                      ? "Visible dans l'Explorateur de contexte et l'historique des requêtes."
                      : "Toutes les requêtes ayant servi cette décision (toutes versions)."
                  }
                  error={idError}
                >
                  <Input
                    id="compliance-id"
                    value={idValue}
                    onChange={(e) => (scope === "request" ? setRequestId(e.target.value) : setMemoryId(e.target.value))}
                    placeholder="00000000-0000-0000-0000-000000000000"
                    className="font-mono"
                  />
                </Field>
              )}
              <div className="flex flex-wrap gap-2">
                <Button asChild size="sm" className={cn(!ready && "pointer-events-none opacity-50")}>
                  <a href={ready ? complianceReportUrl(slug, { ...params, format: "json" }) : undefined} download aria-disabled={!ready}>
                    <Download aria-hidden />
                    Télécharger (JSON)
                  </a>
                </Button>
                <Button asChild size="sm" variant="outline" className={cn(!ready && "pointer-events-none opacity-50")}>
                  <a
                    href={ready ? complianceReportUrl(slug, { ...params, format: "html" }) : undefined}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-disabled={!ready}
                  >
                    <Printer aria-hidden />
                    Version imprimable
                  </a>
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Chaque export est journalisé dans l&apos;audit. Les éléments au-dessus de votre habilitation apparaissent sans titre ni détail.
              </p>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
