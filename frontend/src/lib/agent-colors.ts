/**
 * NOVA agent identity colors by ORBIT agent kind (docs/DESIGN_SYSTEM.md, "Adaptation à ORBIT").
 * Values live in globals.css (--agent-*); consumers set `--agent-color` and use the `.agent-avatar`
 * (14 % disc, 35 % border) or `.agent-text` utilities, which darken/lighten the color for AA text.
 */
import type * as React from "react";

import type { AgentKind } from "@/lib/enums";

const AGENT_COLOR_VARS: Record<AgentKind, string> = {
  product: "var(--agent-product)",
  design: "var(--agent-design)",
  engineering: "var(--agent-engineering)",
  research: "var(--agent-research)",
  custom: "var(--agent-custom)",
};

/** Reserved for « projet » (project-level actors), never for an agent kind. */
export const PROJECT_COLOR_VAR = "var(--agent-project)";

export function agentColorVar(kind: AgentKind | string | null | undefined): string {
  return (kind && AGENT_COLOR_VARS[kind as AgentKind]) || AGENT_COLOR_VARS.custom;
}

/** Inline style setting `--agent-color` for the `.agent-avatar` / `.agent-text` utilities. */
export function agentColorStyle(kind: AgentKind | string | null | undefined): React.CSSProperties {
  return { "--agent-color": agentColorVar(kind) } as React.CSSProperties;
}
