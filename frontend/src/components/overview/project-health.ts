/**
 * Project health, derived on the frontend from the overview payload only (no new business rule on the backend).
 *
 * Levels, from worst to best:
 * - critical       a backend alert is critical, or fewer than half of the documents are indexed;
 * - action         the ingestion pipeline has failed jobs, or documents are not indexed while nothing is running;
 * - watch          no context served in the last 7 days although the project has indexed documents,
 *                  or the context latency p95 is above the 1.5 s objective;
 * - good           otherwise.
 * Governance warnings (proposals to review, contradictions, C3 content) do not degrade the level: they are
 * listed as "points d'attention" because they are normal work items, not malfunctions.
 */
import type { AlertLevel } from "@/lib/enums";
import type { Overview, OverviewAlert } from "@/lib/api/types";

export type HealthLevel = "good" | "watch" | "action" | "critical";

export const HEALTH_META: Record<HealthLevel, { label: string; tone: "green" | "amber" | "orange" | "red" }> = {
  good: { label: "Bon état", tone: "green" },
  watch: { label: "À surveiller", tone: "amber" },
  action: { label: "Action requise", tone: "orange" },
  critical: { label: "Critique", tone: "red" },
};

/** p95 objective of the context engine (docs/ARCHITECTURE.md §9). */
export const CONTEXT_P95_OBJECTIVE_MS = 1500;

export interface HealthCheck {
  ok: boolean;
  label: string;
}

export interface ProjectHealth {
  level: HealthLevel;
  /** Why the level is not "good" (empty when good). */
  reasons: string[];
  /** Number of governance alerts (warning + critical) that ask for someone's attention. */
  attentionCount: number;
  checks: HealthCheck[];
}

const ALERT_ORDER: Record<AlertLevel, number> = { critical: 0, warning: 1, info: 2 };

export function sortAlerts(alerts: readonly OverviewAlert[]): OverviewAlert[] {
  return [...alerts].sort((a, b) => (ALERT_ORDER[a.level] ?? 3) - (ALERT_ORDER[b.level] ?? 3));
}

/**
 * Splits a backend alert message ("1 contradiction non résolue … — arbitrage recommandé.") into a short title
 * and an optional description, so the attention list stays compact.
 */
export function splitAlertMessage(message: string): { title: string; description: string | null } {
  const text = message.trim().replace(/\.$/, "");
  const separator = text.search(/\s[—–-]\s/);
  if (separator > 0) {
    return { title: text.slice(0, separator).trim(), description: capitalize(text.slice(separator + 3).trim()) };
  }
  const colon = text.indexOf(" : ");
  if (colon > 0) return { title: text.slice(0, colon).trim(), description: capitalize(text.slice(colon + 3).trim()) };
  return { title: text, description: null };
}

function capitalize(value: string): string {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

export function computeProjectHealth(overview: Overview): ProjectHealth {
  const { stats, ingestion, context, alerts } = overview;
  const active = ingestion.queued + ingestion.running;
  const notIndexed = Math.max(0, stats.documents - stats.documents_indexed);
  const indexedRatio = stats.documents > 0 ? stats.documents_indexed / stats.documents : 1;
  const reasons: string[] = [];
  let level: HealthLevel = "good";
  const raise = (to: HealthLevel, reason: string) => {
    const rank: Record<HealthLevel, number> = { good: 0, watch: 1, action: 2, critical: 3 };
    if (rank[to] > rank[level]) level = to;
    reasons.push(reason);
  };

  if (alerts.some((alert) => alert.level === "critical")) raise("critical", "Une alerte critique est en cours.");
  if (stats.documents > 0 && indexedRatio < 0.5) raise("critical", "Moins de la moitié des documents sont indexés.");
  if (ingestion.failed > 0) raise("action", `${ingestion.failed} traitement(s) d'ingestion en échec.`);
  else if (notIndexed > 0 && active === 0) raise("action", `${notIndexed} document(s) non indexé(s) sans traitement en cours.`);
  if (stats.documents_indexed > 0 && context.requests_7d === 0) {
    raise("watch", "Aucun contexte servi aux agents depuis 7 jours.");
  }
  if (context.p95_latency_ms !== null && context.p95_latency_ms > CONTEXT_P95_OBJECTIVE_MS) {
    raise("watch", "Latence p95 des contextes au-dessus de l'objectif de 1,5 s.");
  }

  const checks: HealthCheck[] = [
    {
      ok: ingestion.failed === 0,
      label:
        ingestion.failed === 0
          ? active > 0
            ? `Ingestion en cours (${active} traitement${active > 1 ? "s" : ""})`
            : "Ingestion opérationnelle"
          : `${ingestion.failed} traitement${ingestion.failed > 1 ? "s" : ""} en échec`,
    },
    {
      ok: notIndexed === 0,
      label: `${stats.documents_indexed} / ${stats.documents} documents indexés`,
    },
    {
      ok: context.requests_7d > 0 || stats.documents_indexed === 0,
      label:
        context.requests_7d > 0
          ? `${context.requests_7d} contexte${context.requests_7d > 1 ? "s" : ""} servi${context.requests_7d > 1 ? "s" : ""} sur 7 jours`
          : "Aucun contexte servi sur 7 jours",
    },
  ];

  return {
    level,
    reasons,
    attentionCount: alerts.filter((alert) => alert.level !== "info").length,
    checks,
  };
}
