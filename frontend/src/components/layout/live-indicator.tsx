"use client";

import { useLiveState, type LiveState } from "@/lib/live/live-events";
import { cn } from "@/lib/utils";

const META: Record<LiveState, { label: string; hint: string; dot: string }> = {
  connected: { label: "En direct", hint: "Les nouveautés s'affichent automatiquement.", dot: "bg-emerald-500" },
  connecting: { label: "Connexion…", hint: "Connexion au flux en direct.", dot: "bg-amber-500" },
  reconnecting: { label: "Reconnexion…", hint: "Flux interrompu, nouvelle tentative en cours.", dot: "bg-amber-500" },
  polling: { label: "Actualisation périodique", hint: "Flux en direct indisponible : la liste se rafraîchit toutes les 10 s.", dot: "bg-slate-400" },
};

/** Small « En direct » pill showing the state of the live event stream. */
export function LiveIndicator({ className }: { className?: string }) {
  const state = useLiveState();
  const meta = META[state];
  return (
    <span
      role="status"
      title={meta.hint}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2 py-0.5 text-[11px] font-medium text-muted-foreground",
        className,
      )}
    >
      <span className="relative flex size-2" aria-hidden>
        {state === "connected" ? (
          <span className="absolute inline-flex size-full rounded-full bg-emerald-500/60 motion-safe:animate-ping" />
        ) : null}
        <span className={cn("relative inline-flex size-2 rounded-full", meta.dot)} />
      </span>
      {meta.label}
      <span className="sr-only"> — {meta.hint}</span>
    </span>
  );
}
