"use client";

import Link from "next/link";
import { BookOpenText, Sparkles, ThumbsDown, ThumbsUp, Telescope } from "lucide-react";
import { toast } from "sonner";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { errorMessage } from "@/lib/api/client";
import { type AskConfidence, type AskMessage, useAskFeedback } from "@/lib/api/features-ask";
import type { Tone } from "@/lib/enums";
import { cn } from "@/lib/utils";
import { AnswerMarkdown } from "./answer-markdown";

const CONFIDENCE: Record<AskConfidence, { label: string; tone: Tone; hint: string }> = {
  high: { label: "Confiance élevée", tone: "green", hint: "Plusieurs sources concordantes, dont la mémoire validée" },
  medium: { label: "Confiance moyenne", tone: "amber", hint: "Réponse appuyée sur peu de sources : vérifiez-les" },
  low: { label: "Confiance faible", tone: "neutral", hint: "Aucune source suffisamment pertinente" },
};

export interface AnswerMessageProps {
  slug: string;
  conversationId: string;
  message: AskMessage;
  /** Only the latest answer proposes follow-ups. */
  showFollowUps: boolean;
  onFollowUp: (question: string) => void;
  onOpenSources: (message: AskMessage, citation?: string) => void;
  disabled?: boolean;
}

export function AnswerMessage({
  slug,
  conversationId,
  message,
  showFollowUps,
  onFollowUp,
  onOpenSources,
  disabled,
}: AnswerMessageProps) {
  const feedback = useAskFeedback(slug, conversationId);
  const titles = Object.fromEntries(message.citations.map((c) => [c.citation, c.title]));
  const confidence = message.confidence ? CONFIDENCE[message.confidence] : null;

  const rate = (rating: "up" | "down") =>
    feedback.mutate(
      { messageId: message.id, body: { rating } },
      {
        onSuccess: () => toast.success("Merci, votre avis améliore les prochains contextes."),
        onError: (error) => toast.error(errorMessage(error)),
      },
    );

  return (
    <article aria-label="Réponse d'ORBIT" className="flex gap-3">
      <div
        aria-hidden
        className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-soft text-primary"
      >
        <Sparkles className="size-3.5" />
      </div>
      <div className="min-w-0 flex-1 space-y-3 rounded-xl border border-border bg-card p-4 shadow-xs">
        <AnswerMarkdown
          markdown={message.content}
          citationTitles={titles}
          onCitationClick={(citation) => onOpenSources(message, citation)}
        />

        {message.warnings.length > 0 ? (
          <Alert tone="amber" className="text-xs">
            {message.warnings.map((w) => (
              <p key={w}>{w}</p>
            ))}
          </Alert>
        ) : null}

        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
          {confidence ? (
            <SimpleTooltip content={confidence.hint}>
              <span>
                <Badge tone={confidence.tone} dot>
                  {confidence.label}
                </Badge>
              </span>
            </SimpleTooltip>
          ) : null}
          {message.mode ? (
            <SimpleTooltip
              content={
                message.mode === "llm"
                  ? "Rédigée par le LLM à partir des seules sources autorisées par le garde-fou"
                  : "Phrases extraites telles quelles des sources (aucun envoi à un LLM)"
              }
            >
              <span>
                <Badge tone={message.mode === "llm" ? "violet" : "blue"}>
                  {message.mode === "llm" ? "Synthèse LLM" : "Réponse extractive"}
                </Badge>
              </span>
            </SimpleTooltip>
          ) : null}
          {message.citations.length > 0 ? (
            <Button variant="ghost" size="xs" onClick={() => onOpenSources(message)}>
              <BookOpenText aria-hidden />
              {message.citations.length} source{message.citations.length > 1 ? "s" : ""}
            </Button>
          ) : null}
          {message.request_id ? (
            <Button variant="ghost" size="xs" asChild>
              <Link href={`/projects/${encodeURIComponent(slug)}/explorer?request=${encodeURIComponent(message.request_id)}`}>
                <Telescope aria-hidden />
                Contexte servi
              </Link>
            </Button>
          ) : null}
          <div className="ml-auto flex items-center gap-1">
            <SimpleTooltip content="Réponse utile">
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label="Réponse utile"
                aria-pressed={message.rating === 5}
                disabled={feedback.isPending || !message.request_id}
                onClick={() => rate("up")}
                className={cn(message.rating === 5 && "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400")}
              >
                <ThumbsUp aria-hidden />
              </Button>
            </SimpleTooltip>
            <SimpleTooltip content="Réponse à améliorer">
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label="Réponse à améliorer"
                aria-pressed={message.rating === 1}
                disabled={feedback.isPending || !message.request_id}
                onClick={() => rate("down")}
                className={cn(message.rating === 1 && "bg-red-500/10 text-red-600 dark:text-red-400")}
              >
                <ThumbsDown aria-hidden />
              </Button>
            </SimpleTooltip>
          </div>
        </div>

        {showFollowUps && message.follow_ups.length > 0 ? (
          <div className="flex flex-wrap gap-2" aria-label="Suggestions de relance">
            {message.follow_ups.map((q) => (
              <button
                key={q}
                type="button"
                disabled={disabled}
                onClick={() => onFollowUp(q)}
                className="rounded-full border border-border bg-muted/40 px-3 py-1 text-left text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:bg-brand-soft/50 hover:text-foreground disabled:opacity-50"
              >
                {q}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </article>
  );
}
