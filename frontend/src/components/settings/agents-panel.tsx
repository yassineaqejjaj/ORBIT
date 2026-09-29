"use client";

import * as React from "react";
import { Bot, KeyRound, Lock, MoreHorizontal, Plug, Plus, RotateCw, ShieldOff } from "lucide-react";
import { toast } from "sonner";

import { RequireRole } from "@/components/auth/require-role";
import { AgentKindBadge } from "@/components/domain/enum-badge";
import { ClassificationBadge } from "@/components/domain/classification-badge";
import { EnumIcon } from "@/components/domain/enum-icon";
import { RelativeTime } from "@/components/domain/relative-time";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CopyButton } from "@/components/ui/code-block";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Field, fieldDescribedBy } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SimpleSelect, type SimpleSelectOption } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useCurrentProject } from "@/hooks/use-current-project";
import { errorMessage } from "@/lib/api/client";
import { useAgents, useCreateAgent, useMe, useRevokeAgent, useRotateAgentKey } from "@/lib/api/hooks";
import type { Agent, AgentCreated } from "@/lib/api/types";
import {
  AGENT_KIND_META,
  AGENT_KINDS,
  CLASSIFICATION_META,
  CLASSIFICATIONS,
  toClassification,
  type AgentKind,
  type Classification,
} from "@/lib/enums";
import { formatDate, formatDateTime, plural } from "@/lib/format";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";
import { AgentKeyDialog } from "./agent-key-dialog";
import { maskedKey } from "./mcp-snippets";

const NAME_MAX = 120;
const DESCRIPTION_MAX = 2000;

const KIND_OPTIONS: SimpleSelectOption<AgentKind>[] = AGENT_KINDS.map((kind) => ({
  value: kind,
  label: AGENT_KIND_META[kind].label,
  icon: <EnumIcon name={AGENT_KIND_META[kind].icon} />,
}));

function AgentIcon({ kind, active }: { kind: AgentKind; active: boolean }) {
  const meta = AGENT_KIND_META[kind] ?? AGENT_KIND_META.custom;
  return (
    <span
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-lg ring-1 ring-inset [&_svg]:size-4",
        active ? toneClasses(meta.tone).soft : "bg-muted text-muted-foreground ring-border",
      )}
      aria-hidden
    >
      <EnumIcon name={meta.icon} />
    </span>
  );
}

interface CreateAgentDialogProps {
  slug: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Highest clearance the caller may grant (own clearance; admins: C3). */
  maxClearance: Classification;
  onCreated: (created: AgentCreated) => void;
}

function CreateAgentDialog({ slug, open, onOpenChange, maxClearance, onCreated }: CreateAgentDialogProps) {
  const create = useCreateAgent(slug, { meta: { silentError: true } });
  const [name, setName] = React.useState("");
  const [kind, setKind] = React.useState<AgentKind>("product");
  const [description, setDescription] = React.useState("");
  const [clearance, setClearance] = React.useState<Classification>(1);
  const [nameError, setNameError] = React.useState<string | undefined>();
  const [formError, setFormError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setClearance((c) => (c > maxClearance ? maxClearance : c));
      return;
    }
    setName("");
    setKind("product");
    setDescription("");
    setClearance(1 > maxClearance ? maxClearance : 1);
    setNameError(undefined);
    setFormError(null);
    create.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when the dialog opens/closes
  }, [open, maxClearance]);

  const clearanceOptions = React.useMemo<SimpleSelectOption<string>[]>(
    () =>
      CLASSIFICATIONS.map((level) => ({
        value: String(level),
        label: `${CLASSIFICATION_META[level].code} · ${CLASSIFICATION_META[level].label}`,
        description:
          level > maxClearance
            ? "Supérieure à votre propre habilitation"
            : level >= 2
              ? "Peut recevoir des contenus à diffusion restreinte"
              : CLASSIFICATION_META[level].description,
        disabled: level > maxClearance,
      })),
    [maxClearance],
  );

  const busy = create.isPending;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const n = name.trim();
    if (n.length < 2) {
      setNameError("Le nom doit contenir au moins 2 caractères.");
      return;
    }
    if (n.length > NAME_MAX) {
      setNameError(`${NAME_MAX} caractères maximum.`);
      return;
    }
    if (description.length > DESCRIPTION_MAX) {
      setFormError(`La description est limitée à ${DESCRIPTION_MAX} caractères.`);
      return;
    }
    try {
      const result = await create.mutateAsync({
        name: n,
        kind,
        description: description.trim() || undefined,
        clearance,
      });
      onOpenChange(false);
      onCreated(result);
    } catch (error) {
      setFormError(errorMessage(error));
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent size="md">
        <form onSubmit={submit} className="grid gap-5" noValidate>
          <DialogHeader>
            <div className="mb-1 flex size-10 items-center justify-center rounded-lg border border-border bg-brand-soft text-brand">
              <Bot className="size-5" aria-hidden />
            </div>
            <DialogTitle>Nouvel agent</DialogTitle>
            <DialogDescription>
              Chaque agent dispose de sa propre clé API, rattachée à ce projet. Son habilitation plafonne les contenus qu&apos;il
              peut recevoir, quel que soit l&apos;utilisateur pour lequel il agit.
            </DialogDescription>
          </DialogHeader>

          {formError ? <Alert tone="red">{formError}</Alert> : null}

          <Field id="agent-name" label="Nom" required error={nameError}>
            <Input
              id="agent-name"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setNameError(undefined);
              }}
              placeholder="Agent Produit"
              maxLength={NAME_MAX + 10}
              invalid={Boolean(nameError)}
              aria-describedby={fieldDescribedBy("agent-name", { error: nameError })}
              disabled={busy}
              autoFocus
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="agent-kind" label="Type d'agent" required>
              <SimpleSelect<AgentKind> id="agent-kind" value={kind} onValueChange={setKind} options={KIND_OPTIONS} disabled={busy} />
            </Field>
            <Field
              id="agent-clearance"
              label="Habilitation"
              required
              hint={`Au plus ${CLASSIFICATION_META[maxClearance].code} (votre habilitation).`}
            >
              <SimpleSelect<string>
                id="agent-clearance"
                value={String(clearance)}
                onValueChange={(v) => setClearance(toClassification(Number(v)))}
                options={clearanceOptions}
                disabled={busy}
              />
            </Field>
          </div>

          {clearance >= 2 ? (
            <Alert tone={clearance === 3 ? "red" : "amber"} icon={<Lock aria-hidden />}>
              Cet agent pourra recevoir des contenus classifiés {CLASSIFICATION_META[clearance].code} (
              {CLASSIFICATION_META[clearance].label}) lorsqu&apos;il agit pour un membre habilité. Un avertissement accompagne
              chaque contexte concerné.
            </Alert>
          ) : null}

          <Field id="agent-description" label="Description" labelAside={`${description.length}/${DESCRIPTION_MAX}`}>
            <Textarea
              id="agent-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Rédige les spécifications fonctionnelles à partir des comptes rendus et des retours utilisateurs."
              rows={3}
              disabled={busy}
            />
          </Field>

          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
              Annuler
            </Button>
            <Button type="submit" loading={busy} leftIcon={<KeyRound aria-hidden />}>
              Créer et générer la clé
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RowsSkeleton({ columns }: { columns: number }) {
  return (
    <>
      {Array.from({ length: 3 }, (_, i) => (
        <TableRow key={i}>
          <TableCell>
            <div className="flex items-center gap-2.5">
              <Skeleton className="size-8 rounded-lg" />
              <div className="grid gap-1.5">
                <Skeleton className="h-3.5 w-36" />
                <Skeleton className="h-3 w-52" />
              </div>
            </div>
          </TableCell>
          {Array.from({ length: columns - 1 }, (__, j) => (
            <TableCell key={j}>
              <Skeleton className="h-4 w-20" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

export interface AgentsPanelProps {
  /** Switch to the MCP integration tab. */
  onShowMcp?: () => void;
}

/** "Agents" tab: project agents, their clearance and key prefix; owners create, rotate and revoke keys. */
export function AgentsPanel({ onShowMcp }: AgentsPanelProps) {
  const { slug, isOwner, isAdmin } = useCurrentProject();
  const { data: me } = useMe();
  const agents = useAgents(slug);
  const rotate = useRotateAgentKey(slug, { meta: { silentError: true } });
  const revoke = useRevokeAgent(slug, { meta: { silentError: true } });

  const [createOpen, setCreateOpen] = React.useState(false);
  const [issued, setIssued] = React.useState<{ created: AgentCreated; mode: "created" | "rotated" } | null>(null);
  const [toRotate, setToRotate] = React.useState<Agent | null>(null);
  const [toRevoke, setToRevoke] = React.useState<Agent | null>(null);
  const [showRevoked, setShowRevoked] = React.useState(true);

  const maxClearance: Classification = isAdmin ? 3 : toClassification(me?.clearance ?? 0);
  const all = React.useMemo(
    () =>
      [...(agents.data ?? [])].sort(
        (a, b) => Number(b.active) - Number(a.active) || a.name.localeCompare(b.name, "fr"),
      ),
    [agents.data],
  );
  const activeCount = all.filter((a) => a.active).length;
  const revokedCount = all.length - activeCount;
  const list = showRevoked ? all : all.filter((a) => a.active);
  const columns = isOwner ? 7 : 6;

  const confirmRotate = async () => {
    if (!toRotate) return;
    try {
      const result = await rotate.mutateAsync(toRotate.id);
      setToRotate(null);
      setIssued({ created: result, mode: "rotated" });
      toast.success("Clé renouvelée", { description: `L'ancienne clé de « ${result.agent.name} » est révoquée.` });
    } catch (error) {
      toast.error("Impossible de renouveler la clé", { description: errorMessage(error) });
    }
  };

  const confirmRevoke = async () => {
    if (!toRevoke) return;
    try {
      await revoke.mutateAsync(toRevoke.id);
      toast.success("Agent révoqué", { description: `« ${toRevoke.name} » ne peut plus accéder au projet.` });
      setToRevoke(null);
    } catch (error) {
      toast.error("Impossible de révoquer l'agent", { description: errorMessage(error) });
    }
  };

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          {agents.data
            ? `${plural(activeCount, "agent actif", "agents actifs")}${revokedCount > 0 ? ` · ${plural(revokedCount, "révoqué", "révoqués")}` : ""}`
            : "Chargement des agents…"}{" "}
          · chaque appel est authentifié par la clé de l&apos;agent et journalisé.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          {revokedCount > 0 ? (
            <div className="flex items-center gap-2">
              <Switch id="agents-show-revoked" size="sm" checked={showRevoked} onCheckedChange={setShowRevoked} />
              <label htmlFor="agents-show-revoked" className="text-xs text-muted-foreground">
                Afficher les agents révoqués
              </label>
            </div>
          ) : null}
          {onShowMcp ? (
            <Button variant="ghost" size="sm" leftIcon={<Plug aria-hidden />} onClick={onShowMcp}>
              Connecter via MCP
            </Button>
          ) : null}
          <RequireRole min="owner">
            <Button size="sm" leftIcon={<Plus aria-hidden />} onClick={() => setCreateOpen(true)}>
              Nouvel agent
            </Button>
          </RequireRole>
        </div>
      </div>

      {agents.isError ? (
        <ErrorState error={agents.error} onRetry={() => void agents.refetch()} />
      ) : !agents.isPending && all.length === 0 ? (
        <EmptyState
          size="lg"
          icon={<Bot />}
          title="Aucun agent pour ce projet"
          description="Créez un agent (produit, design, ingénierie…) pour lui délivrer une clé API : il pourra alors obtenir des contextes gouvernés via le serveur MCP ou l'API REST."
          action={
            isOwner ? (
              <Button leftIcon={<Plus aria-hidden />} onClick={() => setCreateOpen(true)}>
                Créer un agent
              </Button>
            ) : (
              <p className="text-xs text-muted-foreground">Seuls les propriétaires du projet peuvent créer des agents.</p>
            )
          }
        />
      ) : (
        <Card className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-64">Agent</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Habilitation</TableHead>
                <TableHead>Clé API</TableHead>
                <TableHead>Dernière utilisation</TableHead>
                <TableHead>Statut</TableHead>
                {isOwner ? (
                  <TableHead className="w-12">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                ) : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {agents.isPending ? (
                <RowsSkeleton columns={columns} />
              ) : (
                list.map((agent) => (
                  <TableRow key={agent.id} className={cn(!agent.active && "opacity-60")}>
                    <TableCell>
                      <div className="flex min-w-0 items-center gap-2.5">
                        <AgentIcon kind={agent.kind} active={agent.active} />
                        <div className="grid min-w-0 gap-0.5">
                          <span className={cn("truncate font-medium text-foreground", !agent.active && "line-through")}>
                            {agent.name}
                          </span>
                          <span className="line-clamp-1 text-xs text-muted-foreground" title={agent.description ?? undefined}>
                            {agent.description?.trim() || `Créé le ${formatDate(agent.created_at)}`}
                          </span>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <AgentKindBadge value={agent.kind} />
                    </TableCell>
                    <TableCell>
                      <ClassificationBadge level={agent.clearance} />
                    </TableCell>
                    <TableCell>
                      <span className="inline-flex items-center gap-0.5">
                        <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11.5px] text-foreground">
                          {maskedKey(agent.api_key_prefix)}
                        </code>
                        <CopyButton value={agent.api_key_prefix} label="Copier le préfixe" />
                      </span>
                    </TableCell>
                    <TableCell>
                      {agent.last_used_at ? (
                        <span title={formatDateTime(agent.last_used_at)}>
                          <RelativeTime date={agent.last_used_at} className="text-foreground" />
                        </span>
                      ) : (
                        <span className="text-xs text-subtle-foreground">Jamais utilisé</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {agent.active ? (
                        <Badge tone="green" dot>
                          Actif
                        </Badge>
                      ) : (
                        <Badge tone="neutral" icon={<ShieldOff aria-hidden />}>
                          Révoqué
                        </Badge>
                      )}
                    </TableCell>
                    {isOwner ? (
                      <TableCell>
                        {agent.active ? (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" size="icon-sm" aria-label={`Actions pour ${agent.name}`}>
                                <MoreHorizontal aria-hidden />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem onSelect={() => setToRotate(agent)}>
                                <RotateCw aria-hidden />
                                Renouveler la clé
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem destructive onSelect={() => setToRevoke(agent)}>
                                <ShieldOff aria-hidden />
                                Révoquer l&apos;agent
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        ) : (
                          <SimpleTooltip content="Agent révoqué : créez un nouvel agent pour rétablir l'accès.">
                            <span className="inline-flex size-8 items-center justify-center text-subtle-foreground">
                              <Lock className="size-3.5" aria-hidden />
                            </span>
                          </SimpleTooltip>
                        )}
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </Card>
      )}

      <div className="grid gap-3 rounded-xl border border-border bg-muted/30 p-4 text-xs leading-relaxed text-muted-foreground sm:grid-cols-3">
        <p>
          <span className="font-medium text-foreground">Habilitation.</span> Un contenu n&apos;est servi que si sa classification
          est inférieure ou égale à l&apos;habilitation de l&apos;agent <em>et</em> à celle du membre pour lequel il agit.
        </p>
        <p>
          <span className="font-medium text-foreground">Pour le compte de.</span> Sans <code className="font-mono">on_behalf_of</code>,
          un agent ne reçoit que les contenus ouverts à tout le projet ; les exclusions lui sont communiquées sous forme de compteurs.
        </p>
        <p>
          <span className="font-medium text-foreground">Clés.</span> Format <code className="font-mono">orb_&lt;préfixe&gt;_&lt;secret&gt;</code> ;
          seul le préfixe est visible ici. Le renouvellement révoque immédiatement l&apos;ancienne clé.
        </p>
      </div>

      {isOwner ? (
        <CreateAgentDialog
          slug={slug}
          open={createOpen}
          onOpenChange={setCreateOpen}
          maxClearance={maxClearance}
          onCreated={(created) => {
            setIssued({ created, mode: "created" });
            toast.success("Agent créé", { description: created.agent.name });
          }}
        />
      ) : null}

      <AgentKeyDialog
        slug={slug}
        created={issued?.created ?? null}
        mode={issued?.mode ?? "created"}
        onBehalfOf={me?.id}
        onClose={() => setIssued(null)}
      />

      <ConfirmDialog
        open={toRotate !== null}
        onOpenChange={(open) => {
          if (!open) setToRotate(null);
        }}
        title="Renouveler la clé de cet agent ?"
        description={
          toRotate
            ? `Une nouvelle clé sera générée pour « ${toRotate.name} ». L'ancienne clé (${maskedKey(toRotate.api_key_prefix)}) cessera immédiatement de fonctionner : les clients MCP et intégrations qui l'utilisent devront être mis à jour.`
            : undefined
        }
        confirmLabel="Renouveler la clé"
        onConfirm={confirmRotate}
        loading={rotate.isPending}
      />

      <ConfirmDialog
        open={toRevoke !== null}
        onOpenChange={(open) => {
          if (!open) setToRevoke(null);
        }}
        title="Révoquer cet agent ?"
        description={
          toRevoke
            ? `« ${toRevoke.name} » perdra immédiatement tout accès au projet (API REST et serveur MCP). Son historique de requêtes reste consultable dans l'observabilité et le journal d'audit.`
            : undefined
        }
        destructive
        confirmLabel="Révoquer définitivement"
        onConfirm={confirmRevoke}
        loading={revoke.isPending}
      />
    </div>
  );
}
