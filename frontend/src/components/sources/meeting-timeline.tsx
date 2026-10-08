"use client";

import * as React from "react";
import { CalendarDays, Clock, Mic, Users } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { MeetingMeta, MeetingTurn } from "@/lib/api/types";
import { formatDate, plural } from "@/lib/format";
import { CHART_COLORS } from "@/lib/tones";
import { cn } from "@/lib/utils";

const FORMAT_LABELS: Record<string, string> = {
  vtt: "WebVTT",
  srt: "SRT",
  docx: "Word (DOCX)",
  text: "texte",
  audio: "audio transcrit",
};
const UNKNOWN_SPEAKER = "Intervenant non identifié";

/** `metadata.meeting` of a document detail, or `null` for any other document (§F1). */
export function meetingOf(metadata: Record<string, unknown> | undefined): MeetingMeta | null {
  const value = metadata?.meeting;
  if (!value || typeof value !== "object") return null;
  const meeting = value as MeetingMeta;
  return Array.isArray(meeting.turns) ? meeting : null;
}

export function formatClock(seconds: number | undefined | null): string {
  if (seconds === undefined || seconds === null) return "";
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

function speakerName(turn: MeetingTurn): string {
  return turn.speaker || UNKNOWN_SPEAKER;
}

/** « Réunion » tab: participants, speaking time per speaker, timeline bar and the turn list. */
export function MeetingTimeline({ meeting }: { meeting: MeetingMeta }) {
  const turns = React.useMemo(() => meeting.turns ?? [], [meeting.turns]);
  const [focus, setFocus] = React.useState<string | null>(null);

  const speakers = React.useMemo(() => {
    const names = [...new Set(turns.map(speakerName))];
    return names.map((name, index) => ({ name, color: CHART_COLORS[index % CHART_COLORS.length] }));
  }, [turns]);
  const colorOf = (name: string) => speakers.find((s) => s.name === name)?.color ?? CHART_COLORS[0];

  const duration = meeting.duration_seconds ?? Math.max(0, ...turns.map((t) => t.end ?? t.start ?? 0));
  const timed = duration > 0 && turns.some((t) => t.start !== undefined);
  const talkTime = React.useMemo(() => {
    const totals = new Map<string, number>();
    for (const turn of turns) {
      if (turn.start === undefined) continue;
      const span = Math.max(0, (turn.end ?? turn.start) - turn.start);
      totals.set(speakerName(turn), (totals.get(speakerName(turn)) ?? 0) + span);
    }
    return totals;
  }, [turns]);
  const participants = [...new Set([...(meeting.participants ?? []), ...(meeting.speakers ?? [])])];
  const visible = focus ? turns.filter((t) => speakerName(t) === focus) : turns;

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Mic className="size-4 text-brand" aria-hidden />
            Réunion
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <dl className="grid gap-3 text-[13px] sm:grid-cols-3">
            <div className="grid gap-0.5">
              <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <CalendarDays className="size-3.5" aria-hidden />
                Date
              </dt>
              <dd>{meeting.date ? formatDate(meeting.date) : "Non renseignée"}</dd>
            </div>
            <div className="grid gap-0.5">
              <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Clock className="size-3.5" aria-hidden />
                Durée
              </dt>
              <dd className="tabular-nums">
                {timed ? formatClock(duration) : "—"} · {plural(meeting.turn_count ?? turns.length, "intervention", "interventions")}
              </dd>
            </div>
            <div className="grid gap-0.5">
              <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Users className="size-3.5" aria-hidden />
                Source
              </dt>
              <dd>Transcription {FORMAT_LABELS[meeting.format ?? ""] ?? meeting.format ?? ""}</dd>
            </div>
          </dl>

          {participants.length > 0 ? (
            <div className="flex flex-wrap gap-1.5" aria-label="Participants">
              {participants.map((name) => (
                <Badge key={name} tone="neutral">
                  {name}
                </Badge>
              ))}
            </div>
          ) : null}

          <div className="grid gap-2">
            <p className="text-xs font-medium text-muted-foreground">Intervenants — cliquez pour filtrer</p>
            <ul className="flex flex-wrap gap-2">
              {speakers.map(({ name, color }) => {
                const seconds = talkTime.get(name);
                const active = focus === name;
                return (
                  <li key={name}>
                    <button
                      type="button"
                      onClick={() => setFocus(active ? null : name)}
                      aria-pressed={active}
                      className={cn(
                        "flex items-center gap-2 rounded-md border px-2.5 py-1 text-[13px] transition-colors",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        active ? "border-primary bg-brand-soft" : "border-border hover:bg-muted/60",
                      )}
                    >
                      <span className="size-2.5 rounded-full" style={{ background: color }} aria-hidden />
                      {name}
                      {seconds ? <span className="tabular-nums text-xs text-muted-foreground">{formatClock(seconds)}</span> : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>

          {timed ? (
            <div
              className="relative h-6 overflow-hidden rounded-md bg-surface-3"
              role="img"
              aria-label={`Frise des prises de parole sur ${formatClock(duration)}`}
            >
              {turns.map((turn, index) =>
                turn.start === undefined ? null : (
                  <span
                    key={index}
                    title={`${formatClock(turn.start)} · ${speakerName(turn)}`}
                    className={cn("absolute inset-y-0", focus && focus !== speakerName(turn) && "opacity-25")}
                    style={{
                      left: `${(turn.start / duration) * 100}%`,
                      width: `${Math.max(0.4, (((turn.end ?? turn.start) - turn.start) / duration) * 100)}%`,
                      background: colorOf(speakerName(turn)),
                    }}
                  />
                ),
              )}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <ol className="divide-y divide-border" aria-label="Interventions">
            {visible.map((turn, index) => (
              <li key={index} className="flex gap-3 px-4 py-2.5 text-[13px]">
                <span className="w-14 shrink-0 pt-0.5 font-mono text-xs tabular-nums text-muted-foreground">
                  {formatClock(turn.start)}
                </span>
                <span className="grid min-w-0 gap-0.5">
                  <span className="flex items-center gap-1.5 text-xs font-medium text-foreground">
                    <span className="size-2 rounded-full" style={{ background: colorOf(speakerName(turn)) }} aria-hidden />
                    {speakerName(turn)}
                  </span>
                  <span className="leading-relaxed text-foreground/90">{turn.text}</span>
                </span>
              </li>
            ))}
          </ol>
          {turns.length < (meeting.turn_count ?? 0) ? (
            <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
              Frise limitée aux {turns.length} premières interventions ; le texte complet est dans l&apos;onglet Contenu.
            </p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
