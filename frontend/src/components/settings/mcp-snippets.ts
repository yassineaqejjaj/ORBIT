"use client";

/**
 * MCP integration helpers for the Settings screen: endpoint URL, ready-to-copy client configurations,
 * REST example, and the catalogue of the six ORBIT MCP tools (docs/API.md « MCP », backend `app/mcp_server.py`).
 */
import * as React from "react";

/** Header carrying the agent API key (backend `API_KEY_HEADER`). */
export const AGENT_KEY_HEADER = "X-Orbit-Key";

/** Placeholder used in snippets when the full key is not known (it is only shown once). */
export const AGENT_KEY_PLACEHOLDER = "<CLE_API_DE_L_AGENT>";

/** Masked representation of an agent key from its public prefix (`orb_<prefix>_<secret>`). */
export function maskedKey(prefix: string): string {
  return `orb_${prefix}_••••••••`;
}

/** Example task used in the REST example (demo project Atlas). */
export const EXAMPLE_TASK =
  "Rédiger la spécification fonctionnelle du module de réservation pour le pilote de Lyon";

function subscribeNoop(): () => void {
  return () => undefined;
}

/** `window.location.origin` on the client, "" during server rendering (hydration-safe). */
export function useOrigin(): string {
  return React.useSyncExternalStore(
    subscribeNoop,
    () => window.location.origin,
    () => "",
  );
}

/** Public MCP endpoint (Next.js proxies `/mcp` to the API). */
export function mcpEndpoint(origin: string): string {
  return `${origin || ""}/mcp`;
}

/** Stable MCP server name for a project, e.g. `orbit-atlas`. */
export function mcpServerName(slug: string): string {
  const clean = slug.toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "");
  return clean ? `orbit-${clean}` : "orbit";
}

export interface SnippetInput {
  origin: string;
  slug: string;
  /** Full key, or undefined to use the placeholder. */
  apiKey?: string;
}

/** JSON configuration for MCP clients using the `mcpServers` format (streamable HTTP transport). */
export function mcpJsonConfig({ origin, slug, apiKey }: SnippetInput): string {
  const config = {
    mcpServers: {
      [mcpServerName(slug)]: {
        type: "http",
        url: mcpEndpoint(origin),
        headers: { [AGENT_KEY_HEADER]: apiKey ?? AGENT_KEY_PLACEHOLDER },
      },
    },
  };
  return `${JSON.stringify(config, null, 2)}\n`;
}

/** One-line registration for command-line MCP clients (streamable HTTP + custom header). */
export function mcpCliCommand({ origin, slug, apiKey }: SnippetInput): string {
  return [
    `claude mcp add --transport http ${mcpServerName(slug)} \\`,
    `  ${mcpEndpoint(origin)} \\`,
    `  --header "${AGENT_KEY_HEADER}: ${apiKey ?? AGENT_KEY_PLACEHOLDER}"`,
  ].join("\n");
}

function shellSingleQuote(value: string): string {
  return `'${value.replace(/'/g, `'"'"'`)}'`;
}

/** `curl` call of `POST /api/v1/projects/{slug}/context` authenticated with the agent key. */
export function curlContextExample({
  origin,
  slug,
  apiKey,
  onBehalfOf,
  task = EXAMPLE_TASK,
}: SnippetInput & { onBehalfOf?: string; task?: string }): string {
  const body: Record<string, unknown> = { task, token_budget: 4000 };
  if (onBehalfOf) body.on_behalf_of = onBehalfOf;
  const json = JSON.stringify(body, null, 2);
  return [
    `curl -sS -X POST "${origin || ""}/api/v1/projects/${encodeURIComponent(slug)}/context" \\`,
    `  -H "${AGENT_KEY_HEADER}: ${apiKey ?? AGENT_KEY_PLACEHOLDER}" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d ${shellSingleQuote(json)}`,
  ].join("\n");
}

export interface McpToolParam {
  name: string;
  type: string;
  required?: boolean;
  description: string;
}

export interface McpToolMeta {
  name: string;
  title: string;
  description: string;
  readOnly: boolean;
  params: McpToolParam[];
  returns: string;
}

/** The six tools exposed by the ORBIT MCP server (same engine and governance as the REST API). */
export const MCP_TOOLS: readonly McpToolMeta[] = [
  {
    name: "get_context",
    title: "Obtenir un contexte gouverné",
    description:
      "Assemble le contexte d'une tâche : décisions en vigueur, besoins, contraintes et extraits de sources cités [S1]…, filtrés selon les droits, la fraîcheur et la pertinence.",
    readOnly: false,
    params: [
      { name: "task", type: "string", required: true, description: "Tâche en langage naturel" },
      { name: "intent", type: "Intent", description: "Intention ; déduite de la tâche si omise" },
      { name: "token_budget", type: "500–32000", description: "Budget de tokens (défaut : paramètre du projet)" },
      { name: "scopes", type: "MemoryScope[]", description: "Portées mémoire (défaut : toutes)" },
      { name: "on_behalf_of", type: "UUID | e-mail", description: "Membre pour lequel l'agent travaille (hérite de ses droits)" },
      { name: "session_id", type: "string", description: "Session de travail dont les tours récents sont réinjectés" },
      { name: "base_snapshot", type: "string", description: "Snapshot de départ : « nom », « nom@3 » ou « nom@latest »" },
      { name: "save_snapshot", type: "string", description: "Enregistre le contexte comme nouvelle version de ce snapshot" },
    ],
    returns: "context, citations[], exclusion_summary, request_id, snapshot",
  },
  {
    name: "get_snapshot",
    title: "Lire un snapshot de contexte",
    description: "Relit une version d'un snapshot de contexte partagé (ex. spec-atlas@2), limité aux droits de l'agent.",
    readOnly: true,
    params: [
      { name: "name", type: "string", required: true, description: "Nom du snapshot, ex. spec-atlas" },
      { name: "version", type: "number | \"latest\"", description: "Version (défaut : la plus récente)" },
    ],
    returns: "Snapshot (contenu, éléments, empreinte)",
  },
  {
    name: "search_sources",
    title: "Rechercher dans les sources",
    description:
      "Recherche hybride (BM25 + sémantique) dans les documents indexés du projet ; données personnelles masquées, résultats limités aux droits de l'agent.",
    readOnly: true,
    params: [
      { name: "query", type: "string", required: true, description: "Recherche en langage naturel" },
      { name: "limit", type: "1–50", description: "Nombre maximal de résultats (défaut 10)" },
    ],
    returns: "SearchHit[]",
  },
  {
    name: "propose_memory",
    title: "Proposer une mémoire",
    description:
      "Propose une décision, un besoin, une contrainte, un risque ou un fait. L'élément reste « proposé » jusqu'à validation humaine.",
    readOnly: false,
    params: [
      { name: "kind", type: "MemoryKind", required: true, description: "decision, requirement, constraint, risk, fact…" },
      { name: "title", type: "string", required: true, description: "Titre court et autoportant" },
      { name: "content", type: "string", required: true, description: "Énoncé complet" },
      { name: "scope", type: "project | long_term", description: "Portée (défaut : project)" },
      { name: "provenance_document_ids", type: "UUID[]", description: "Documents sources justifiant la proposition" },
    ],
    returns: "MemoryItem (statut proposed)",
  },
  {
    name: "record_turn",
    title: "Enregistrer un tour de session",
    description: "Ajoute un tour (user, agent ou tool) à la mémoire court terme d'une session de travail.",
    readOnly: false,
    params: [
      { name: "session_id", type: "string", required: true, description: "Identifiant de session" },
      { name: "role", type: "user | agent | tool", required: true, description: "Auteur du tour" },
      { name: "content", type: "string", required: true, description: "Contenu du tour" },
    ],
    returns: "turns, expires_at",
  },
  {
    name: "send_feedback",
    title: "Évaluer un contexte",
    description: "Évalue (1 à 5) un contexte servi par get_context, à partir de son request_id.",
    readOnly: false,
    params: [
      { name: "request_id", type: "UUID", required: true, description: "request_id renvoyé par get_context" },
      { name: "rating", type: "1–5", required: true, description: "Note de 1 (inutile) à 5 (parfait)" },
      { name: "comment", type: "string", description: "Commentaire libre" },
    ],
    returns: "id",
  },
];
