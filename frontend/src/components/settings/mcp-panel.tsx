"use client";

import * as React from "react";
import {
  Activity,
  BookOpenCheck,
  CircleCheck,
  CircleX,
  KeyRound,
  Network,
  Plug,
  ShieldCheck,
  Terminal,
  Wrench,
} from "lucide-react";

import { AgentKindBadge } from "@/components/domain/enum-badge";
import { ClassificationBadge } from "@/components/domain/classification-badge";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CodeBlock, CopyButton } from "@/components/ui/code-block";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/hooks/use-current-project";
import { useAgents, useMe } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";
import {
  AGENT_KEY_HEADER,
  curlContextExample,
  MCP_TOOLS,
  mcpCliCommand,
  mcpEndpoint,
  mcpJsonConfig,
  mcpServerName,
  maskedKey,
  useOrigin,
} from "./mcp-snippets";

type ConfigTab = "json" | "cli";

type ProbeState =
  | { status: "idle" }
  | { status: "checking" }
  | { status: "ok"; detail: string }
  | { status: "error"; detail: string };

/**
 * Checks that `/mcp` answers and enforces authentication (an anonymous request must get 401),
 * without sending any credential.
 */
function useEndpointProbe(endpoint: string) {
  const [state, setState] = React.useState<ProbeState>({ status: "idle" });
  const probe = React.useCallback(async () => {
    setState({ status: "checking" });
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json, text/event-stream" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "ping" }),
        credentials: "omit",
        cache: "no-store",
        signal: controller.signal,
      });
      if (response.status === 401 || response.status === 403) {
        setState({
          status: "ok",
          detail: "Serveur MCP joignable : les appels sans clé d'agent sont bien refusés (401).",
        });
      } else if (response.status === 404) {
        setState({ status: "error", detail: "Point d'accès introuvable (404) : le serveur MCP n'est pas monté." });
      } else if (response.status >= 500) {
        setState({ status: "error", detail: `Le serveur MCP est indisponible (HTTP ${response.status}).` });
      } else {
        setState({ status: "error", detail: `Réponse inattendue sans authentification (HTTP ${response.status}).` });
      }
    } catch (error) {
      const aborted = error instanceof DOMException && error.name === "AbortError";
      setState({
        status: "error",
        detail: aborted ? "Délai dépassé : le serveur MCP ne répond pas." : "Impossible de joindre le serveur MCP.",
      });
    } finally {
      window.clearTimeout(timer);
    }
  }, [endpoint]);
  return { state, probe };
}

function Step({ index, title, children }: { index: number; title: string; children: React.ReactNode }) {
  return (
    <li className="relative flex gap-3">
      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary text-[12px] font-semibold text-primary-foreground">
        {index}
      </span>
      <div className="grid min-w-0 gap-1 pb-1">
        <p className="text-[13px] font-medium text-foreground">{title}</p>
        <div className="text-xs leading-relaxed text-muted-foreground">{children}</div>
      </div>
    </li>
  );
}

export interface McpPanelProps {
  /** Switch to the Agents tab (create / rotate a key). */
  onShowAgents?: () => void;
}

/** "Intégration MCP" tab: what MCP is, endpoint, ready-to-copy client config, REST example and tool catalogue. */
export function McpPanel({ onShowAgents }: McpPanelProps) {
  const { slug, isOwner } = useCurrentProject();
  const { data: me } = useMe();
  const agents = useAgents(slug);
  const origin = useOrigin();
  const endpoint = mcpEndpoint(origin);
  const [configTab, setConfigTab] = React.useState<ConfigTab>("json");
  const { state: probeState, probe } = useEndpointProbe(endpoint);

  const activeAgents = (agents.data ?? []).filter((a) => a.active);
  const input = { origin, slug };
  const config = configTab === "json" ? mcpJsonConfig(input) : mcpCliCommand(input);
  const curl = curlContextExample({ ...input, onBehalfOf: me?.id });

  return (
    <div className="grid gap-4">
      <Card className="overflow-hidden">
        <div className="grid gap-6 p-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
          <div className="grid content-start gap-3">
            <div className="flex items-center gap-2">
              <span className="flex size-8 items-center justify-center rounded-lg border border-border bg-brand-soft text-brand">
                <Plug className="size-4" aria-hidden />
              </span>
              <h3 className="text-sm font-semibold tracking-tight text-foreground">Model Context Protocol (MCP)</h3>
              <Badge tone="teal" variant="outline">
                Streamable HTTP
              </Badge>
            </div>
            <p className="text-[13px] leading-relaxed text-muted-foreground">
              MCP est le protocole ouvert qui permet aux assistants et frameworks d&apos;agents IA de découvrir et d&apos;appeler des
              outils externes. ORBIT expose un serveur MCP : vos agents y obtiennent un contexte <strong className="font-medium text-foreground">gouverné</strong> —
              pertinent, frais, sourcé et filtré selon les droits — avec exactement le même moteur que l&apos;explorateur de
              contexte.
            </p>
            <ul className="grid gap-1.5 text-xs text-muted-foreground">
              <li className="flex items-start gap-2">
                <ShieldCheck className="mt-px size-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />
                Authentification par clé d&apos;agent (en-tête <code className="font-mono text-foreground">{AGENT_KEY_HEADER}</code> ou{" "}
                <code className="font-mono text-foreground">Authorization: Bearer orb_…</code>), limitée à ce projet.
              </li>
              <li className="flex items-start gap-2">
                <ShieldCheck className="mt-px size-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />
                Données personnelles toujours caviardées, contenus hors habilitation jamais transmis (pas même leur titre).
              </li>
              <li className="flex items-start gap-2">
                <ShieldCheck className="mt-px size-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />
                Chaque appel est tracé : requêtes visibles dans l&apos;observabilité, actions dans le journal d&apos;audit.
              </li>
            </ul>
          </div>
          <ol className="grid content-start gap-3 rounded-lg border border-border bg-muted/30 p-4">
            <Step index={1} title="Créer un agent et copier sa clé">
              La clé complète n&apos;est affichée qu&apos;une fois, avec une configuration pré-remplie.{" "}
              {onShowAgents ? (
                <button
                  type="button"
                  onClick={onShowAgents}
                  className="rounded font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {isOwner ? "Gérer les agents" : "Voir les agents"}
                </button>
              ) : null}
            </Step>
            <Step index={2} title="Déclarer le serveur dans votre client MCP">
              Copiez la configuration ci-dessous et remplacez la clé par celle de l&apos;agent.
            </Step>
            <Step index={3} title="Appeler get_context au début de chaque tâche">
              Renseignez <code className="font-mono">on_behalf_of</code> (UUID ou e-mail du membre) pour hériter de ses droits ;
              citez les sources [S1]… et terminez par <code className="font-mono">send_feedback</code>.
            </Step>
          </ol>
        </div>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card className="flex flex-col">
          <CardHeader className="flex-row items-center gap-2">
            <Network className="size-4 text-muted-foreground" aria-hidden />
            <CardTitle>Point d&apos;accès</CardTitle>
            <CardAction>
              <Button
                variant="secondary"
                size="xs"
                leftIcon={<Activity aria-hidden />}
                onClick={() => void probe()}
                loading={probeState.status === "checking"}
                disabled={!origin}
              >
                Tester la connexion
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="grid gap-3">
            <div className="flex items-center gap-1 rounded-md border border-input bg-muted/40 pl-3 pr-1">
              {origin ? (
                <code className="h-9 min-w-0 flex-1 truncate font-mono text-[13px] leading-9 text-foreground">{endpoint}</code>
              ) : (
                <Skeleton className="my-2.5 h-4 flex-1" />
              )}
              <CopyButton value={endpoint} label="Copier l'URL du serveur MCP" />
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-3">
              <div className="grid gap-0.5">
                <dt className="text-muted-foreground">Transport</dt>
                <dd className="font-medium text-foreground">Streamable HTTP (sans état)</dd>
              </div>
              <div className="grid gap-0.5">
                <dt className="text-muted-foreground">En-tête</dt>
                <dd className="font-mono text-foreground">{AGENT_KEY_HEADER}</dd>
              </div>
              <div className="grid gap-0.5">
                <dt className="text-muted-foreground">Nom suggéré</dt>
                <dd className="font-mono text-foreground">{mcpServerName(slug)}</dd>
              </div>
            </dl>
            {probeState.status === "ok" ? (
              <Alert tone="green" icon={<CircleCheck aria-hidden />}>
                {probeState.detail}
              </Alert>
            ) : probeState.status === "error" ? (
              <Alert tone="red" icon={<CircleX aria-hidden />}>
                {probeState.detail}
              </Alert>
            ) : null}
          </CardContent>
        </Card>

        <Card className="flex flex-col">
          <CardHeader className="flex-row items-center gap-2">
            <KeyRound className="size-4 text-muted-foreground" aria-hidden />
            <CardTitle>Clés d&apos;agents actives</CardTitle>
            <span className="ml-auto text-xs tabular-nums text-muted-foreground">
              {agents.data ? activeAgents.length : "…"}
            </span>
          </CardHeader>
          <CardContent className="grid flex-1 content-start gap-2">
            {agents.isPending ? (
              Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-9" />)
            ) : agents.isError ? (
              <p className="text-xs text-destructive">Impossible de charger les agents du projet.</p>
            ) : activeAgents.length === 0 ? (
              <div className="grid justify-items-start gap-2 rounded-lg border border-dashed border-border px-3 py-4">
                <p className="text-[13px] text-muted-foreground">Aucun agent actif : créez-en un pour obtenir une clé.</p>
                {onShowAgents && isOwner ? (
                  <Button size="xs" variant="secondary" onClick={onShowAgents}>
                    Créer un agent
                  </Button>
                ) : null}
              </div>
            ) : (
              <ul className="grid gap-1.5">
                {activeAgents.map((agent) => (
                  <li
                    key={agent.id}
                    className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-border bg-background px-3 py-2"
                  >
                    <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground">{agent.name}</span>
                    <AgentKindBadge value={agent.kind} withIcon={false} />
                    <ClassificationBadge level={agent.clearance} showLabel={false} />
                    <code className="font-mono text-[11.5px] text-muted-foreground">{maskedKey(agent.api_key_prefix)}</code>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-xs text-muted-foreground">
              Identifiez une clé par son préfixe. Clé perdue ? Renouvelez-la depuis l&apos;onglet Agents : la configuration
              pré-remplie est affichée à ce moment-là.
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader className="flex-row flex-wrap items-center gap-2">
            <Plug className="size-4 text-muted-foreground" aria-hidden />
            <CardTitle>Configuration du client MCP</CardTitle>
            <CardAction>
              <SegmentedControl<ConfigTab>
                size="sm"
                value={configTab}
                onValueChange={setConfigTab}
                aria-label="Format de configuration"
                options={[
                  { value: "json", label: "JSON" },
                  { value: "cli", label: "Ligne de commande", icon: <Terminal aria-hidden /> },
                ]}
              />
            </CardAction>
          </CardHeader>
          <CardContent className="grid gap-2">
            <CodeBlock
              code={config}
              language={configTab === "json" ? "json" : "bash"}
              title={configTab === "json" ? "mcp.json" : "Enregistrement du serveur"}
              maxHeightClassName="max-h-72"
            />
            <p className="text-xs text-muted-foreground">
              Format <code className="font-mono">mcpServers</code> reconnu par la plupart des clients MCP (transport
              <code className="font-mono"> http</code> = Streamable HTTP). Remplacez{" "}
              <code className="font-mono">&lt;CLE_API_DE_L_AGENT&gt;</code> par la clé de l&apos;agent.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center gap-2">
            <Terminal className="size-4 text-muted-foreground" aria-hidden />
            <CardTitle>Sans client MCP : API REST</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2">
            <CodeBlock code={curl} language="bash" title="POST /api/v1/projects/{slug}/context" maxHeightClassName="max-h-72" />
            <p className="text-xs text-muted-foreground">
              Même moteur, même gouvernance. <code className="font-mono">on_behalf_of</code> est pré-rempli avec votre identifiant :
              l&apos;agent hérite alors de vos droits, dans la limite de sa propre habilitation.
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center gap-2">
          <Wrench className="size-4 text-muted-foreground" aria-hidden />
          <CardTitle>Outils exposés</CardTitle>
          <CardDescription className="ml-1 hidden sm:block">{MCP_TOOLS.length} outils, découverts automatiquement par le client</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="grid gap-3 md:grid-cols-2">
            {MCP_TOOLS.map((tool) => (
              <li key={tool.name} className="grid content-start gap-2 rounded-lg border border-border bg-background p-3.5">
                <div className="flex flex-wrap items-center gap-2">
                  <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[12.5px] font-semibold text-foreground">
                    {tool.name}
                  </code>
                  <span className="text-[13px] font-medium text-foreground">{tool.title}</span>
                  <Badge
                    tone={tool.readOnly ? "blue" : "violet"}
                    variant="outline"
                    className="ml-auto"
                    icon={tool.readOnly ? <BookOpenCheck aria-hidden /> : undefined}
                  >
                    {tool.readOnly ? "Lecture seule" : "Écriture tracée"}
                  </Badge>
                </div>
                <p className="text-xs leading-relaxed text-muted-foreground">{tool.description}</p>
                <div className="flex flex-wrap gap-1">
                  {tool.params.map((param) => (
                    <span
                      key={param.name}
                      title={`${param.description} (${param.type})`}
                      className={cn(
                        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[11px] ring-1 ring-inset",
                        param.required
                          ? "bg-brand-soft/60 text-foreground ring-primary/30"
                          : "bg-muted/60 text-muted-foreground ring-border",
                      )}
                    >
                      {param.name}
                      {param.required ? <span className="text-destructive" aria-label="obligatoire">*</span> : null}
                    </span>
                  ))}
                </div>
                <p className="text-[11.5px] text-subtle-foreground">
                  Retourne : <span className="font-mono">{tool.returns}</span>
                </p>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
