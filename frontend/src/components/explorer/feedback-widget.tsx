"use client";

import * as React from "react";
import { ChevronDown, Flag, MessageSquareHeart, Send, Star } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage } from "@/lib/api/client";
import { useSendContextFeedback } from "@/lib/api/hooks";
import type { ContextFeedback, ContextItem, FeedbackItemFlag } from "@/lib/api/types";
import { ACTOR_TYPE_META, FEEDBACK_FLAGS, FEEDBACK_FLAG_META, getMeta, type FeedbackFlag } from "@/lib/enums";
import { formatDateTime, truncate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { CitationBadge } from "./citation-badge";
import { StarRating } from "./star-rating";

const RATING_LABELS = ["", "Inutilisable", "Peu utile", "Correct", "Utile", "Excellent"] as const;
const COMMENT_MAX = 4000;

export interface FeedbackWidgetProps {
  slug: string;
  requestId: string;
  items: ContextItem[];
  /** Feedback already recorded for this request (stored request detail). */
  existing?: ContextFeedback[];
}

function StarInput({ value, onChange, disabled }: { value: number; onChange: (v: number) => void; disabled?: boolean }) {
  const [hover, setHover] = React.useState(0);
  const shown = hover || value;
  const refs = React.useRef<Array<HTMLButtonElement | null>>([]);

  const onKeyDown = (e: React.KeyboardEvent, n: number) => {
    let next = n;
    if (e.key === "ArrowRight" || e.key === "ArrowUp") next = Math.min(5, n + 1);
    else if (e.key === "ArrowLeft" || e.key === "ArrowDown") next = Math.max(1, n - 1);
    else return;
    e.preventDefault();
    onChange(next);
    refs.current[next - 1]?.focus();
  };

  return (
    <div className="flex items-center gap-3">
      <div role="radiogroup" aria-label="Note du contexte" className="flex items-center gap-0.5" onMouseLeave={() => setHover(0)}>
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            ref={(el) => {
              refs.current[n - 1] = el;
            }}
            type="button"
            role="radio"
            aria-checked={value === n}
            aria-label={`${n} sur 5 — ${RATING_LABELS[n]}`}
            tabIndex={value === n || (value === 0 && n === 1) ? 0 : -1}
            disabled={disabled}
            onMouseEnter={() => setHover(n)}
            onFocus={() => setHover(0)}
            onClick={() => onChange(n)}
            onKeyDown={(e) => onKeyDown(e, n)}
            className="rounded p-0.5 transition-transform hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
          >
            <Star
              aria-hidden
              className={cn(
                "size-6 transition-colors",
                n <= shown ? "fill-amber-400 text-amber-400" : "fill-transparent text-border-strong",
              )}
            />
          </button>
        ))}
      </div>
      <span className="text-[13px] font-medium text-muted-foreground" aria-live="polite">
        {shown ? RATING_LABELS[shown] : "Choisissez une note"}
      </span>
    </div>
  );
}

function ExistingFeedback({ feedback }: { feedback: ContextFeedback[] }) {
  if (feedback.length === 0) return null;
  return (
    <div className="grid gap-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-subtle-foreground">Retours enregistrés ({feedback.length})</p>
      <ul className="grid gap-2">
        {feedback.map((f) => (
          <li key={f.id} className="rounded-md border border-border bg-muted/30 px-3 py-2">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <StarRating value={f.rating} />
              <span className="font-medium text-foreground">{f.actor_label || getMeta(ACTOR_TYPE_META, f.actor_type).label}</span>
              <span className="text-subtle-foreground">{formatDateTime(f.created_at)}</span>
            </div>
            {f.comment ? <p className="mt-1 text-[13px] leading-relaxed text-foreground/90">{f.comment}</p> : null}
            {f.item_flags.length > 0 ? (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {f.item_flags.map((flag, i) => (
                  <Badge key={`${flag.citation}-${i}`} tone={getMeta(FEEDBACK_FLAG_META, flag.flag).tone} icon={<Flag aria-hidden />}>
                    {flag.citation} · {getMeta(FEEDBACK_FLAG_META, flag.flag).label}
                  </Badge>
                ))}
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Rating (1–5), comment and per-citation flags posted to `POST /context/requests/{id}/feedback`. */
export function FeedbackWidget({ slug, requestId, items, existing = [] }: FeedbackWidgetProps) {
  const [rating, setRating] = React.useState(0);
  const [comment, setComment] = React.useState("");
  const [flags, setFlags] = React.useState<Record<string, FeedbackFlag>>({});
  const [flagsOpen, setFlagsOpen] = React.useState(false);
  const [sent, setSent] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Reset the form when another request is displayed.
  const [prevRequest, setPrevRequest] = React.useState(requestId);
  if (prevRequest !== requestId) {
    setPrevRequest(requestId);
    setRating(0);
    setComment("");
    setFlags({});
    setSent(false);
    setError(null);
  }

  const send = useSendContextFeedback(slug, { meta: { silentError: true } });
  const flagCount = Object.keys(flags).length;

  const toggleFlag = (citation: string, flag: FeedbackFlag) =>
    setFlags((prev) => {
      const next = { ...prev };
      if (next[citation] === flag) delete next[citation];
      else next[citation] = flag;
      return next;
    });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (rating < 1) {
      setError("Choisissez une note de 1 à 5 étoiles.");
      return;
    }
    setError(null);
    const item_flags: FeedbackItemFlag[] = Object.entries(flags).map(([citation, flag]) => ({ citation, flag }));
    send.mutate(
      {
        requestId,
        body: {
          rating,
          ...(comment.trim() ? { comment: comment.trim() } : {}),
          ...(item_flags.length ? { item_flags } : {}),
        },
      },
      {
        onSuccess: () => {
          setSent(true);
          setRating(0);
          setComment("");
          setFlags({});
          toast.success(
            item_flags.some((f) => f.flag === "outdated")
              ? "Merci ! Les éléments signalés obsolètes feront l'objet d'une proposition d'obsolescence."
              : "Merci pour votre retour, il alimente l'évaluation des contextes.",
          );
        },
        onError: (err) => setError(errorMessage(err)),
      },
    );
  };

  return (
    <div className="grid gap-4">
      {sent ? (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3.5 py-2.5 text-[13px] text-emerald-900 dark:border-emerald-400/25 dark:bg-emerald-400/10 dark:text-emerald-100">
          <span className="flex items-center gap-2">
            <MessageSquareHeart className="size-4" aria-hidden />
            Retour enregistré. Merci !
          </span>
          <Button variant="ghost" size="xs" onClick={() => setSent(false)}>
            Donner un autre avis
          </Button>
        </div>
      ) : (
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <div className="grid gap-2">
            <Label>Ce contexte était-il utile pour la tâche ?</Label>
            <StarInput value={rating} onChange={setRating} disabled={send.isPending} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`feedback-comment-${requestId}`}>Commentaire (optionnel)</Label>
            <Textarea
              id={`feedback-comment-${requestId}`}
              rows={2}
              value={comment}
              maxLength={COMMENT_MAX}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Ex. il manque la contrainte d'accessibilité RGAA, la décision PWA est bien présente…"
              disabled={send.isPending}
            />
          </div>

          {items.length > 0 ? (
            <div className="rounded-lg border border-border">
              <button
                type="button"
                onClick={() => setFlagsOpen((v) => !v)}
                aria-expanded={flagsOpen}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] font-medium hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Flag className="size-3.5 text-muted-foreground" aria-hidden />
                Signaler des éléments (optionnel)
                {flagCount > 0 ? <Badge tone="amber">{flagCount}</Badge> : null}
                <ChevronDown className={cn("ml-auto size-4 text-subtle-foreground transition-transform", flagsOpen && "rotate-180")} aria-hidden />
              </button>
              {flagsOpen ? (
                <ul className="grid max-h-80 gap-1 overflow-y-auto border-t border-border p-2">
                  {items.map((item) => (
                    <li key={item.citation} className="flex flex-col gap-1.5 rounded-md px-1.5 py-1.5 hover:bg-muted/40 sm:flex-row sm:items-center">
                      <span className="flex min-w-0 flex-1 items-center gap-2">
                        <CitationBadge citation={item.citation} />
                        <span className="truncate text-[13px] text-foreground" title={item.title}>
                          {truncate(item.title, 80)}
                        </span>
                      </span>
                      <span className="flex shrink-0 gap-1" role="group" aria-label={`Signalement de ${item.citation}`}>
                        {FEEDBACK_FLAGS.map((flag) => {
                          const meta = FEEDBACK_FLAG_META[flag];
                          const on = flags[item.citation] === flag;
                          return (
                            <button
                              key={flag}
                              type="button"
                              aria-pressed={on}
                              title={meta.description}
                              onClick={() => toggleFlag(item.citation, flag)}
                              disabled={send.isPending}
                              className={cn(
                                "h-6 rounded-md px-2 text-[11.5px] font-medium ring-1 ring-inset transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                                on
                                  ? flag === "wrong"
                                    ? "bg-red-600 text-white ring-transparent dark:bg-red-500"
                                    : flag === "outdated"
                                      ? "bg-amber-500 text-amber-950 ring-transparent dark:bg-amber-400"
                                      : "bg-slate-700 text-white ring-transparent dark:bg-slate-300 dark:text-slate-900"
                                  : "text-muted-foreground ring-border hover:bg-accent hover:text-foreground",
                              )}
                            >
                              {meta.label}
                            </button>
                          );
                        })}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}

          {error ? (
            <p role="alert" className="text-xs font-medium text-destructive">
              {error}
            </p>
          ) : null}

          <div className="flex justify-end">
            <Button type="submit" size="sm" loading={send.isPending} leftIcon={<Send aria-hidden />}>
              Envoyer le retour
            </Button>
          </div>
        </form>
      )}
      <ExistingFeedback feedback={existing} />
    </div>
  );
}
