"use client";

import * as React from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { MessageCircleQuestion, MessagesSquare, ShieldCheck, Sparkles } from "lucide-react";

import { UserAvatar } from "@/components/domain/user-avatar";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { useCurrentProject } from "@/hooks/use-current-project";
import { errorMessage } from "@/lib/api/client";
import { type AskMessage, askApi, askKeys, useAsk, useAskConversation } from "@/lib/api/features-ask";
import { useMe } from "@/lib/api/hooks";
import type { ContextItem, User } from "@/lib/api/types";
import { AnswerMessage } from "./answer-message";
import { AskComposer } from "./ask-composer";
import { ConversationList } from "./conversation-list";
import { SourcesSheet } from "./sources-sheet";
import { TeamsPanel } from "./teams-panel";

export const EXAMPLE_QUESTIONS = [
  "Pourquoi a-t-on choisi une PWA ?",
  "Qu'a-t-on décidé sur l'authentification ?",
  "Quels sont les principaux risques du projet ?",
  "Quelles contraintes s'appliquent au mode hors ligne ?",
];

export function AskView() {
  const { slug, isOwner } = useCurrentProject();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const conversationId = searchParams.get("conversation");

  const conversation = useAskConversation(slug, conversationId);
  const ask = useAsk(slug);
  const [pendingQuestion, setPendingQuestion] = React.useState<string | null>(null);
  const [failed, setFailed] = React.useState<{ question: string; error: unknown } | null>(null);
  const [sources, setSources] = React.useState<{ citations: ContextItem[]; active: string | null } | null>(null);
  const [teamsOpen, setTeamsOpen] = React.useState(false);
  const bottomRef = React.useRef<HTMLDivElement>(null);

  const select = React.useCallback(
    (id: string | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (id) params.set("conversation", id);
      else params.delete("conversation");
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
      setFailed(null);
    },
    [pathname, router, searchParams],
  );

  const submit = async (question: string) => {
    setPendingQuestion(question);
    setFailed(null);
    try {
      const out = await ask.mutateAsync({ question, conversation_id: conversationId });
      await qc.prefetchQuery({
        queryKey: askKeys.conversation(slug, out.conversation_id),
        queryFn: ({ signal }) => askApi.getConversation(slug, out.conversation_id, { signal }),
      });
      if (out.conversation_id !== conversationId) select(out.conversation_id);
    } catch (error) {
      setFailed({ question, error });
    } finally {
      setPendingQuestion(null);
    }
  };

  const messages = conversationId ? (conversation.data?.messages ?? []) : [];
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [messages.length, pendingQuestion]);

  const openSources = (message: AskMessage, citation?: string) =>
    setSources({ citations: message.citations, active: citation ?? null });

  const busy = ask.isPending || pendingQuestion !== null;
  const empty = !conversationId && !pendingQuestion && !failed;

  return (
    <div className="flex flex-col">
      <PageHeader
        icon={<MessageCircleQuestion />}
        title="Demander à ORBIT"
        description="Des réponses sourcées, construites sur le moteur de contexte gouverné : chaque affirmation cite sa source."
        actions={
          isOwner ? (
            <Button variant="secondary" size="sm" onClick={() => setTeamsOpen(true)}>
              <MessagesSquare aria-hidden />
              Connecter Microsoft Teams
            </Button>
          ) : null
        }
      />

      <div className="grid gap-6 lg:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="lg:sticky lg:top-4 lg:max-h-[calc(100vh-8rem)] lg:self-start">
          <ConversationList slug={slug} activeId={conversationId} onSelect={select} />
        </aside>

        <section aria-label="Conversation" className="flex min-h-[60vh] flex-col gap-4">
          {empty ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-5 rounded-xl border border-dashed border-border bg-muted/20 px-6 py-12 text-center">
              <div className="flex size-11 items-center justify-center rounded-full bg-brand-soft text-primary">
                <Sparkles className="size-5" aria-hidden />
              </div>
              <div className="space-y-1.5">
                <h2 className="text-base font-semibold">Que voulez-vous savoir sur ce projet ?</h2>
                <p className="mx-auto max-w-md text-[13px] text-muted-foreground">
                  ORBIT répond uniquement à partir des décisions, besoins et documents que vous avez le droit de voir. Sans
                  source pertinente, il le dit.
                </p>
              </div>
              <div className="flex max-w-xl flex-wrap justify-center gap-2">
                {EXAMPLE_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => void submit(q)}
                    className="rounded-full border border-border bg-card px-3.5 py-1.5 text-[13px] shadow-xs transition-colors hover:border-primary/40 hover:bg-brand-soft/50"
                  >
                    {q}
                  </button>
                ))}
              </div>
              <p className="flex items-center gap-1.5 text-xs text-subtle-foreground">
                <ShieldCheck className="size-3.5" aria-hidden />
                Vos conversations sont privées.
              </p>
            </div>
          ) : conversationId && conversation.isLoading ? (
            <div className="space-y-4">
              <Skeleton className="ml-auto h-10 w-2/3" />
              <Skeleton className="h-36 w-full" />
            </div>
          ) : conversationId && conversation.error ? (
            <ErrorState error={conversation.error} onRetry={() => void conversation.refetch()} />
          ) : (
            <ol className="flex flex-col gap-5" aria-live="polite">
              {messages.map((m) =>
                m.role === "user" ? (
                  <li key={m.id}>
                    <UserQuestion text={m.content} user={me} />
                  </li>
                ) : (
                  <li key={m.id}>
                    <AnswerMessage
                      slug={slug}
                      conversationId={conversationId ?? ""}
                      message={m}
                      showFollowUps={m.id === lastAssistant?.id && !busy}
                      onFollowUp={(q) => void submit(q)}
                      onOpenSources={openSources}
                      disabled={busy}
                    />
                  </li>
                ),
              )}
              {pendingQuestion ? (
                <li className="space-y-4">
                  <UserQuestion text={pendingQuestion} user={me} />
                  <div className="flex items-center gap-2 pl-10 text-[13px] text-muted-foreground" role="status">
                    <Spinner className="size-4" />
                    Recherche dans la mémoire gouvernée du projet…
                  </div>
                </li>
              ) : null}
              {failed ? (
                <li>
                  <Alert
                    tone="red"
                    title="La question n'a pas pu aboutir"
                    action={
                      <Button size="xs" variant="secondary" onClick={() => void submit(failed.question)}>
                        Réessayer
                      </Button>
                    }
                  >
                    {errorMessage(failed.error)}
                  </Alert>
                </li>
              ) : null}
            </ol>
          )}
          <div ref={bottomRef} />
          <div className="sticky bottom-0 mt-auto bg-gradient-to-t from-background via-background to-transparent pb-2 pt-4">
            <AskComposer onSubmit={(q) => void submit(q)} pending={busy} autoFocus />
            <p className="mt-1.5 text-center text-[11px] text-subtle-foreground">
              Réponses citées, même gouvernance que le moteur de contexte · aucune donnée au-dessus du plafond n&apos;est
              envoyée à un LLM externe.
            </p>
          </div>
        </section>
      </div>

      <SourcesSheet
        slug={slug}
        open={sources !== null}
        onOpenChange={(open) => (open ? null : setSources(null))}
        citations={sources?.citations ?? []}
        active={sources?.active ?? null}
      />
      {isOwner ? <TeamsPanel slug={slug} open={teamsOpen} onOpenChange={setTeamsOpen} /> : null}
    </div>
  );
}

function UserQuestion({ text, user }: { text: string; user: User | undefined }) {
  return (
    <div className="flex items-start justify-end gap-3">
      <p className="max-w-[80%] whitespace-pre-wrap rounded-xl rounded-tr-sm bg-primary px-3.5 py-2 text-[13.5px] text-primary-foreground shadow-xs">
        {text}
      </p>
      <UserAvatar user={user} size="sm" />
    </div>
  );
}
