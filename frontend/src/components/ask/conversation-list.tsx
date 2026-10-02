"use client";

import { MessageSquareText, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { RelativeTime } from "@/components/domain/relative-time";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/client";
import { useAskConversations, useDeleteAskConversation } from "@/lib/api/features-ask";
import { cn } from "@/lib/utils";

export interface ConversationListProps {
  slug: string;
  activeId: string | null;
  onSelect: (id: string | null) => void;
}

/** Private history of the caller's conversations (nobody else sees them, owners included). */
export function ConversationList({ slug, activeId, onSelect }: ConversationListProps) {
  const { data, isLoading, error, refetch } = useAskConversations(slug);
  const remove = useDeleteAskConversation(slug);

  return (
    <nav aria-label="Historique des conversations" className="flex min-h-0 flex-col gap-2">
      <Button variant="secondary" size="sm" onClick={() => onSelect(null)} className="justify-start">
        <Plus aria-hidden />
        Nouvelle conversation
      </Button>
      <p className="px-1 pt-2 text-[11px] font-medium uppercase tracking-[0.06em] text-subtle-foreground">Historique</p>
      {isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-11 w-full" />
          ))}
        </div>
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} size="sm" variant="plain" />
      ) : !data || data.length === 0 ? (
        <p className="px-1 text-xs text-muted-foreground">Vos questions apparaîtront ici. Elles restent privées.</p>
      ) : (
        <ul className="space-y-1 overflow-y-auto">
          {data.map((c) => (
            <li key={c.id} className="group relative">
              <button
                type="button"
                onClick={() => onSelect(c.id)}
                aria-current={c.id === activeId ? "page" : undefined}
                className={cn(
                  "flex w-full flex-col gap-0.5 rounded-lg px-2.5 py-2 pr-8 text-left transition-colors",
                  c.id === activeId ? "bg-accent text-accent-foreground" : "hover:bg-muted/60",
                )}
              >
                <span className="line-clamp-2 text-[13px] font-medium leading-snug">{c.title}</span>
                <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  {c.channel === "teams" ? (
                    <>
                      <MessageSquareText className="size-3" aria-hidden /> Teams ·
                    </>
                  ) : null}
                  <RelativeTime date={c.updated_at} />
                </span>
              </button>
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label={`Supprimer la conversation « ${c.title} »`}
                className="absolute right-1 top-1.5 opacity-0 focus-visible:opacity-100 group-hover:opacity-100"
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(c.id, {
                    onSuccess: () => {
                      if (c.id === activeId) onSelect(null);
                      toast.success("Conversation supprimée");
                    },
                    onError: (e) => toast.error(errorMessage(e)),
                  })
                }
              >
                <Trash2 aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </nav>
  );
}
