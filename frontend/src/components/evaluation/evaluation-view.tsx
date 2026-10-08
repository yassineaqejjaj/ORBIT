"use client";

import * as React from "react";
import { Download, FlaskConical, GitCompare, Play, Plus, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableEmptyRow, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useCurrentProject } from "@/hooks/use-current-project";
import { errorMessage } from "@/lib/api/client";
import {
  evalApi,
  type EvalRunSummary,
  useEvalCompare,
  useEvalMutation,
  useEvalRun,
  useEvalRuns,
  useEvalSet,
  useEvalSets,
  useJudgements,
} from "@/lib/api/features-eval";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;
const METRICS = [
  { key: "recall", label: "Rappel@k" },
  { key: "ndcg", label: "nDCG@k" },
  { key: "sufficiency", label: "Suffisance" },
  { key: "citation_faithfulness", label: "Fidélité des citations" },
] as const;

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)} %`;
}

function RunStatus({ run }: { run: EvalRunSummary }) {
  if (run.status === "queued" || run.status === "running")
    return (
      <Badge tone="blue" size="sm" pulse>
        {run.status === "queued" ? "En file" : "En cours"}
      </Badge>
    );
  if (run.status === "failed") return <Badge tone="danger" size="sm">Échec technique</Badge>;
  if (run.passed === false) return <Badge tone="warning" size="sm">Sous le seuil</Badge>;
  if (run.passed) return <Badge tone="success" size="sm">Réussie</Badge>;
  return <Badge tone="neutral" size="sm">Sans question</Badge>;
}

/** Suivi → Évaluation (§E1 bench, §E3 LLM judge). */
export function EvaluationView() {
  const { slug, project, canEdit, isOwner } = useCurrentProject();
  const sets = useEvalSets(slug);
  const runs = useEvalRuns(slug);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [openRun, setOpenRun] = React.useState<string | null>(null);
  const [compare, setCompare] = React.useState<string[]>([]);
  const setId = selected ?? sets.data?.[0]?.id ?? null;
  const detail = useEvalSet(slug, setId);
  const run = useEvalRun(slug, openRun);
  const compared = useEvalCompare(slug, compare[0] ?? null, compare[1] ?? null);

  const [name, setName] = React.useState("");
  const [question, setQuestion] = React.useState("");
  const [expected, setExpected] = React.useState("");
  const onError = (error: unknown) => toast.error(errorMessage(error));
  const createSet = useEvalMutation(slug, (n: string) => evalApi.createSet(slug, { name: n }));
  const addCase = useEvalMutation(slug, (body: { question: string; ids: string[] }) =>
    evalApi.addCase(slug, setId as string, {
      question: body.question,
      expected: body.ids.map((id) => ({ type: "memory" as const, id })),
    }),
  );
  const deleteCase = useEvalMutation(slug, (caseId: string) => evalApi.deleteCase(slug, setId as string, caseId));
  const generate = useEvalMutation(slug, () => evalApi.generate(slug, setId as string, 10));
  const start = useEvalMutation(slug, () => evalApi.startRun(slug, setId as string));

  const ids = expected.match(UUID_RE) ?? [];
  const toggleCompare = (id: string) =>
    setCompare((current) => (current.includes(id) ? current.filter((x) => x !== id) : [...current, id].slice(-2)));

  return (
    <div className="flex min-w-0 flex-col">
      <PageHeader
        icon={<FlaskConical />}
        eyebrow={project.name}
        title="Évaluation"
        description="Questions de référence du projet rejouées sur le moteur de contexte : rappel, nDCG, suffisance et fidélité des citations, avec historique, comparaison et LLM-juge sur échantillon."
      />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div className="grid content-start gap-5">
          <Card>
            <CardHeader>
              <CardTitle>Jeux de questions de référence</CardTitle>
              <CardDescription>Chaque question liste les éléments attendus (lignées de mémoire).</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
              {sets.isLoading ? <Skeleton className="h-20" /> : null}
              {sets.error ? <ErrorState error={sets.error} onRetry={() => sets.refetch()} size="sm" /> : null}
              {sets.data?.length === 0 ? (
                <EmptyState size="sm" title="Aucun jeu" description="Créez un jeu puis ajoutez ou générez des questions." />
              ) : null}
              <ul className="grid gap-1.5">
                {sets.data?.map((s) => (
                  <li key={s.id}>
                    <button
                      type="button"
                      onClick={() => setSelected(s.id)}
                      className={cn(
                        "flex w-full items-center justify-between gap-2 rounded-md border px-3 py-2 text-left text-[13px]",
                        s.id === setId ? "border-brand bg-surface" : "border-border hover:bg-surface",
                      )}
                    >
                      <span className="min-w-0 truncate font-medium">{s.name}</span>
                      <span className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                        {s.cases_count} q.
                        {s.last_run ? <RunStatus run={s.last_run} /> : null}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              {canEdit ? (
                <form
                  className="flex gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    createSet.mutate(name.trim(), { onSuccess: (s) => (setSelected((s as { id: string }).id), setName("")), onError });
                  }}
                >
                  <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nom du nouveau jeu" aria-label="Nom du nouveau jeu" />
                  <Button type="submit" size="sm" variant="outline" disabled={!name.trim() || createSet.isPending}>
                    <Plus aria-hidden />
                    Créer
                  </Button>
                </form>
              ) : null}
            </CardContent>
          </Card>

          {setId && detail.data ? (
            <Card>
              <CardHeader>
                <CardTitle>{detail.data.name}</CardTitle>
                <CardDescription>{detail.data.description || `${detail.data.cases.length} question(s)`}</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4">
                {canEdit ? (
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" onClick={() => start.mutate(undefined, { onSuccess: () => toast.success("Évaluation lancée"), onError })} disabled={start.isPending || detail.data.cases.length === 0}>
                      <Play aria-hidden />
                      Lancer l&apos;évaluation
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={generate.isPending}
                      onClick={() =>
                        generate.mutate(undefined, {
                          onSuccess: (out) => toast.success(`${(out as unknown[]).length} question(s) générée(s) depuis les décisions validées`),
                          onError,
                        })
                      }
                    >
                      <Sparkles aria-hidden />
                      Générer depuis les décisions
                    </Button>
                  </div>
                ) : null}
                <ul className="grid gap-2">
                  {detail.data.cases.map((c) => (
                    <li key={c.id} className="flex items-start justify-between gap-2 rounded-md border border-border px-3 py-2">
                      <div className="min-w-0">
                        <p className="text-[13px] text-foreground">{c.question}</p>
                        <p className="text-xs text-muted-foreground">
                          Attendu : {c.expected.map((e) => e.title || e.id.slice(0, 8)).join(" · ") || "—"}
                          {c.origin === "generated" ? " · générée" : ""}
                        </p>
                      </div>
                      {canEdit ? (
                        <Button size="icon" variant="ghost" aria-label="Retirer la question" onClick={() => deleteCase.mutate(c.id, { onError })}>
                          <Trash2 aria-hidden />
                        </Button>
                      ) : null}
                    </li>
                  ))}
                </ul>
                {canEdit ? (
                  <form
                    className="grid gap-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      addCase.mutate(
                        { question: question.trim(), ids },
                        { onSuccess: () => (setQuestion(""), setExpected("")), onError },
                      );
                    }}
                  >
                    <Field id="eval-question" label="Nouvelle question">
                      <Input id="eval-question" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Où est hébergé le portail ?" />
                    </Field>
                    <Field id="eval-expected" label="Éléments attendus" hint="Identifiants de lignée des items mémoire (copiés depuis Mémoire), séparés par des espaces.">
                      <Textarea id="eval-expected" rows={2} value={expected} onChange={(e) => setExpected(e.target.value)} className="font-mono text-xs" />
                    </Field>
                    <Button type="submit" size="sm" variant="outline" disabled={question.trim().length < 3 || addCase.isPending}>
                      <Plus aria-hidden />
                      Ajouter ({ids.length} attendu{ids.length > 1 ? "s" : ""})
                    </Button>
                  </form>
                ) : null}
              </CardContent>
            </Card>
          ) : null}
        </div>

        <div className="grid content-start gap-5">
          <Card>
            <CardHeader>
              <CardTitle>Historique</CardTitle>
              <CardDescription>
                Sélectionnez deux exécutions pour les comparer. En CI : <code className="font-mono">python -m app.admin eval --project {slug}</code>
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8"><span className="sr-only">Comparer</span></TableHead>
                    <TableHead>Date</TableHead>
                    {METRICS.map((m) => (
                      <TableHead key={m.key} className="text-right">{m.label}</TableHead>
                    ))}
                    <TableHead>Statut</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.data?.length === 0 ? <TableEmptyRow colSpan={7}>Aucune exécution pour l&apos;instant.</TableEmptyRow> : null}
                  {runs.data?.map((r) => (
                    <TableRow key={r.id} className={cn("cursor-pointer", openRun === r.id && "bg-surface")} onClick={() => setOpenRun(r.id)}>
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" aria-label="Comparer cette exécution" checked={compare.includes(r.id)} onChange={() => toggleCompare(r.id)} />
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs">
                        {formatDateTime(r.created_at)} <span className="text-muted-foreground">· {r.trigger} · k={r.k}</span>
                      </TableCell>
                      {METRICS.map((m) => (
                        <TableCell key={m.key} className="text-right font-mono text-xs">{pct(r.metrics[m.key])}</TableCell>
                      ))}
                      <TableCell><RunStatus run={r} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {compared.data ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><GitCompare className="size-4" aria-hidden />Comparaison</CardTitle>
                <CardDescription>
                  {formatDateTime(compared.data.base.created_at)} → {formatDateTime(compared.data.target.created_at)}
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3">
                <div className="flex flex-wrap gap-2">
                  {METRICS.map((m) => {
                    const d = compared.data.delta[m.key];
                    return (
                      <Badge key={m.key} tone={d === null || d === undefined || d === 0 ? "neutral" : d > 0 ? "success" : "danger"} size="sm">
                        {m.label} {d === null || d === undefined ? "—" : `${d > 0 ? "+" : ""}${Math.round(d * 100)} pts`}
                      </Badge>
                    );
                  })}
                </div>
                <ul className="grid gap-1 text-xs">
                  {compared.data.cases.map((c) => (
                    <li key={c.case_id} className="flex justify-between gap-2">
                      <span className="truncate">{c.question}</span>
                      <span className="shrink-0 font-mono">{pct(c.base_recall)} → {pct(c.target_recall)}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}

          {run.data ? (
            <Card>
              <CardHeader>
                <CardTitle>Détail par question</CardTitle>
                <CardDescription>
                  Seuil de rappel {pct(run.data.min_recall)} · classement {String(run.data.config.reranker ?? "—")}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {run.data.error ? <Alert tone="red">{run.data.error}</Alert> : null}
                <ul className="grid gap-2">
                  {run.data.cases.map((c) => (
                    <li key={c.case_id} className="rounded-md border border-border px-3 py-2">
                      <p className="text-[13px]">{c.question}</p>
                      <p className="text-xs text-muted-foreground">
                        Rappel {pct(c.recall)} · nDCG {pct(c.ndcg)} · suffisance {pct(c.sufficiency)} · citations {pct(c.citation_faithfulness)}
                        {c.found.length ? ` · trouvé : ${c.found.join(", ")}` : " · attendu non servi"}
                      </p>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}

          <JudgeCard slug={slug} isOwner={isOwner} />
        </div>
      </div>
    </div>
  );
}

function JudgeCard({ slug, isOwner }: { slug: string; isOwner: boolean }) {
  const judgements = useJudgements(slug);
  const data = judgements.data;
  return (
    <Card>
      <CardHeader>
        <CardTitle>LLM-juge (échantillon des contextes servis)</CardTitle>
        <CardDescription>
          {data
            ? `Échantillon ${pct(data.sample_rate)} · moyenne sur ${data.window_days} j : ${pct(data.window_average)} (${data.window_count} verdicts) · seuil d'alerte ${pct(data.threshold)}`
            : "Note de suffisance ; jamais de contenu C2/C3 vers un LLM externe."}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {data?.alerts.map((a) => (
          <Alert key={a} tone="amber">{a}</Alert>
        ))}
        {data && data.sample_rate === 0 ? (
          <p className="text-xs text-muted-foreground">Désactivé : réglez ORBIT_JUDGE_SAMPLE_RATE pour échantillonner les contextes servis.</p>
        ) : null}
        <ul className="grid gap-1.5 text-xs">
          {data?.items.slice(0, 8).map((j) => (
            <li key={j.request_id} className="flex items-start justify-between gap-2">
              <span className="min-w-0 truncate">{j.task}</span>
              <span className="flex shrink-0 items-center gap-1.5">
                <Badge tone={j.method === "llm" ? "accent" : "neutral"} size="sm">
                  {j.method === "llm" ? "LLM" : j.method === "skipped_guardrail" ? "garde-fou" : "déterministe"}
                </Badge>
                <span className="font-mono">{pct(j.score)}</span>
              </span>
            </li>
          ))}
        </ul>
        {isOwner ? (
          <Button asChild size="sm" variant="outline" className="justify-self-start">
            <a href={evalApi.exportUrl(slug)} download>
              <Download aria-hidden />
              Export FORGE (NDJSON)
            </a>
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}
