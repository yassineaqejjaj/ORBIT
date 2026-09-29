"use client";

import * as React from "react";
import { KeyRound, ShieldAlert } from "lucide-react";

import { AgentKindBadge } from "@/components/domain/enum-badge";
import { ClassificationBadge } from "@/components/domain/classification-badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { CodeBlock } from "@/components/ui/code-block";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { SegmentedControl } from "@/components/ui/segmented-control";
import type { AgentCreated } from "@/lib/api/types";
import { curlContextExample, mcpCliCommand, mcpJsonConfig, useOrigin } from "./mcp-snippets";

type SnippetTab = "mcp" | "cli" | "curl";

export interface AgentKeyDialogProps {
  slug: string;
  /** Result of POST /agents or /agents/{id}/rotate; the dialog is open while non-null. */
  created: AgentCreated | null;
  /** "created" after a creation, "rotated" after a key rotation. */
  mode: "created" | "rotated";
  /** Current user id, pre-filled as `on_behalf_of` in the REST example. */
  onBehalfOf?: string;
  onClose: () => void;
}

/**
 * Shows a freshly issued agent API key exactly once, with ready-to-use MCP / REST snippets embedding it.
 * Closing requires an explicit acknowledgement: ORBIT only stores the key hash.
 */
export function AgentKeyDialog({ slug, created, mode, onBehalfOf, onClose }: AgentKeyDialogProps) {
  const origin = useOrigin();
  const [acknowledged, setAcknowledged] = React.useState(false);
  const [tab, setTab] = React.useState<SnippetTab>("mcp");
  // Keep the last key rendered during the closing animation.
  const [last, setLast] = React.useState<AgentCreated | null>(created);
  React.useEffect(() => {
    if (created) setLast(created);
  }, [created]);
  const view = created ?? last;
  const open = created !== null;

  React.useEffect(() => {
    if (open) {
      setAcknowledged(false);
      setTab("mcp");
    }
  }, [open, created?.api_key]);

  const snippet = React.useMemo(() => {
    if (!view) return "";
    const input = { origin, slug, apiKey: view.api_key };
    if (tab === "cli") return mcpCliCommand(input);
    if (tab === "curl") return curlContextExample({ ...input, onBehalfOf });
    return mcpJsonConfig(input);
  }, [view, origin, slug, tab, onBehalfOf]);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && acknowledged) onClose();
      }}
    >
      <DialogContent
        size="lg"
        hideClose
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => {
          if (!acknowledged) e.preventDefault();
        }}
      >
        {view ? (
          <div className="grid gap-5">
            <DialogHeader>
              <div className="mb-1 flex size-10 items-center justify-center rounded-lg border border-border bg-brand-soft text-brand">
                <KeyRound className="size-5" aria-hidden />
              </div>
              <DialogTitle>
                {mode === "rotated" ? "Nouvelle clé API" : "Agent créé"} — {view.agent.name}
              </DialogTitle>
              <DialogDescription>
                {mode === "rotated"
                  ? "L'ancienne clé est révoquée immédiatement : mettez à jour les clients qui l'utilisaient."
                  : "L'agent peut désormais obtenir des contextes gouvernés via le serveur MCP ou l'API REST."}
              </DialogDescription>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <AgentKindBadge value={view.agent.kind} />
                <ClassificationBadge level={view.agent.clearance} prefix="Habilitation" />
              </div>
            </DialogHeader>

            <div
              role="alert"
              className="flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 px-3.5 py-3 text-[13px] text-amber-950 dark:border-amber-400/35 dark:bg-amber-400/10 dark:text-amber-100"
            >
              <ShieldAlert className="mt-px size-4 shrink-0" aria-hidden />
              <p className="leading-relaxed">
                <strong className="font-semibold">Copiez cette clé maintenant : elle ne sera plus jamais affichée.</strong>{" "}
                ORBIT n&apos;en conserve qu&apos;une empreinte (SHA-256). Stockez-la dans un gestionnaire de secrets, jamais dans
                un dépôt de code. En cas de perte, renouvelez-la.
              </p>
            </div>

            <CodeBlock code={view.api_key} title="Clé API de l'agent" wrap hideCopy={false} maxHeightClassName="max-h-24" />

            <div className="grid gap-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-[13px] font-medium text-foreground">Configuration prête à l&apos;emploi</p>
                <SegmentedControl<SnippetTab>
                  size="sm"
                  value={tab}
                  onValueChange={setTab}
                  aria-label="Format de configuration"
                  options={[
                    { value: "mcp", label: "Client MCP (JSON)" },
                    { value: "cli", label: "Ligne de commande" },
                    { value: "curl", label: "API REST (curl)" },
                  ]}
                />
              </div>
              <CodeBlock
                code={snippet}
                language={tab === "mcp" ? "json" : "bash"}
                title={tab === "mcp" ? "mcp.json" : tab === "cli" ? "Enregistrement du serveur MCP" : "POST /context"}
                maxHeightClassName="max-h-60"
              />
            </div>

            <DialogFooter className="items-stretch sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="agent-key-ack"
                  checked={acknowledged}
                  onCheckedChange={(checked) => setAcknowledged(checked === true)}
                />
                <Label htmlFor="agent-key-ack" className="text-[13px] font-normal leading-snug">
                  J&apos;ai copié la clé et je l&apos;ai stockée en lieu sûr
                </Label>
              </div>
              <Button onClick={onClose} disabled={!acknowledged}>
                Terminer
              </Button>
            </DialogFooter>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
