/**
 * « Demander à ORBIT » (F4) and Microsoft Teams integration: types, endpoints and TanStack Query hooks.
 * Kept apart from the shared types/endpoints/hooks modules (feature ownership, docs/FEATURES.md).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type ApiError, http, request } from "./client";
import { queryKeys } from "./query-keys";
import type { MemoryScope } from "@/lib/enums";

import type { ContextItem, ISODateString, UUID } from "./types";

/* -------------------------------------------------------------------------- */
/* Types                                                                      */
/* -------------------------------------------------------------------------- */

/** Memory-card fields added to memory items by the LLM-assisted extraction (F3). */
export interface MemoryCardFields {
  rationale?: string | null;
  decided_by?: string | null;
  confidence_reason?: string | null;
}

export type AskMode = "llm" | "extractive";
export type AskConfidence = "high" | "medium" | "low";
export type AskChannel = "web" | "teams" | "api";

export interface AskIn {
  question: string;
  conversation_id?: UUID | null;
  scopes?: MemoryScope[] | null;
  token_budget?: number | null;
}

export interface AskOut {
  answer: string;
  citations: ContextItem[];
  confidence: AskConfidence;
  follow_ups: string[];
  request_id: UUID | null;
  conversation_id: UUID;
  message_id: UUID;
  mode: AskMode;
  warnings: string[];
}

export interface AskMessage {
  id: UUID;
  role: "user" | "assistant";
  content: string;
  citations: ContextItem[];
  confidence: AskConfidence | null;
  mode: AskMode | null;
  follow_ups: string[];
  warnings: string[];
  request_id: UUID | null;
  rating: 1 | 5 | null;
  created_at: ISODateString;
}

export interface AskConversationSummary {
  id: UUID;
  title: string;
  channel: AskChannel;
  message_count: number;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface AskConversationDetail extends AskConversationSummary {
  messages: AskMessage[];
}

export interface AskFeedbackIn {
  rating: "up" | "down";
  comment?: string | null;
}

export interface TeamsUserLink {
  teams_id: string;
  user_id: UUID;
}

export interface TeamsUserLinkOut extends TeamsUserLink {
  user_label: string;
  is_member: boolean;
}

export interface TeamsIntegration {
  configured: boolean;
  enabled: boolean;
  encryption_available: boolean;
  webhook_path: string;
  app_url: string;
  user_mapping: TeamsUserLinkOut[];
  updated_at: ISODateString | null;
}

export interface TeamsIntegrationIn {
  secret?: string | null;
  enabled: boolean;
  app_url?: string | null;
  user_mapping: TeamsUserLink[];
}

/* -------------------------------------------------------------------------- */
/* Endpoints                                                                  */
/* -------------------------------------------------------------------------- */

const p = (slug: string) => `/projects/${encodeURIComponent(slug)}`;
type Opts = { signal?: AbortSignal };

export const askApi = {
  ask: (slug: string, body: AskIn) => http.post<AskOut>(`${p(slug)}/ask`, body),
  listConversations: (slug: string, opts: Opts = {}) =>
    http.get<AskConversationSummary[]>(`${p(slug)}/ask/conversations`, opts),
  getConversation: (slug: string, id: UUID, opts: Opts = {}) =>
    http.get<AskConversationDetail>(`${p(slug)}/ask/conversations/${encodeURIComponent(id)}`, opts),
  deleteConversation: (slug: string, id: UUID) =>
    http.delete(`${p(slug)}/ask/conversations/${encodeURIComponent(id)}`),
  sendFeedback: (slug: string, messageId: UUID, body: AskFeedbackIn) =>
    http.post<AskMessage>(`${p(slug)}/ask/messages/${encodeURIComponent(messageId)}/feedback`, body),
  getTeams: (slug: string, opts: Opts = {}) => http.get<TeamsIntegration>(`${p(slug)}/integrations/teams`, opts),
  putTeams: (slug: string, body: TeamsIntegrationIn) =>
    request<TeamsIntegration>(`${p(slug)}/integrations/teams`, { method: "PUT", json: body }),
  deleteTeams: (slug: string) => http.delete(`${p(slug)}/integrations/teams`),
};

/* -------------------------------------------------------------------------- */
/* Query keys & hooks                                                         */
/* -------------------------------------------------------------------------- */

export const askKeys = {
  all: (slug: string) => [...queryKeys.project.all(slug), "ask"] as const,
  conversations: (slug: string) => [...askKeys.all(slug), "conversations"] as const,
  conversation: (slug: string, id: UUID) => [...askKeys.all(slug), "conversation", id] as const,
  teams: (slug: string) => [...queryKeys.project.all(slug), "integrations", "teams"] as const,
};

export function useAskConversations(slug: string) {
  return useQuery<AskConversationSummary[], ApiError>({
    queryKey: askKeys.conversations(slug),
    queryFn: ({ signal }) => askApi.listConversations(slug, { signal }),
    enabled: Boolean(slug),
  });
}

export function useAskConversation(slug: string, id: UUID | null | undefined) {
  return useQuery<AskConversationDetail, ApiError>({
    queryKey: askKeys.conversation(slug, id ?? ""),
    queryFn: ({ signal }) => askApi.getConversation(slug, id as string, { signal }),
    enabled: Boolean(slug && id),
  });
}

export function useAsk(slug: string) {
  const qc = useQueryClient();
  return useMutation<AskOut, ApiError, AskIn>({
    mutationFn: (body) => askApi.ask(slug, body),
    onSuccess: (out) =>
      Promise.all([
        qc.invalidateQueries({ queryKey: askKeys.conversations(slug) }),
        qc.invalidateQueries({ queryKey: askKeys.conversation(slug, out.conversation_id) }),
        qc.invalidateQueries({ queryKey: queryKeys.project.context.all(slug) }),
      ]),
  });
}

export function useDeleteAskConversation(slug: string) {
  const qc = useQueryClient();
  return useMutation<unknown, ApiError, UUID>({
    mutationFn: (id) => askApi.deleteConversation(slug, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: askKeys.conversations(slug) }),
  });
}

export function useAskFeedback(slug: string, conversationId: UUID | null | undefined) {
  const qc = useQueryClient();
  return useMutation<AskMessage, ApiError, { messageId: UUID; body: AskFeedbackIn }>({
    mutationFn: ({ messageId, body }) => askApi.sendFeedback(slug, messageId, body),
    onSuccess: () =>
      conversationId ? qc.invalidateQueries({ queryKey: askKeys.conversation(slug, conversationId) }) : undefined,
  });
}

export function useTeamsIntegration(slug: string, enabled = true) {
  return useQuery<TeamsIntegration, ApiError>({
    queryKey: askKeys.teams(slug),
    queryFn: ({ signal }) => askApi.getTeams(slug, { signal }),
    enabled: Boolean(slug) && enabled,
  });
}

export function useSaveTeamsIntegration(slug: string) {
  const qc = useQueryClient();
  return useMutation<TeamsIntegration, ApiError, TeamsIntegrationIn>({
    mutationFn: (body) => askApi.putTeams(slug, body),
    onSuccess: (data) => qc.setQueryData(askKeys.teams(slug), data),
  });
}

export function useDeleteTeamsIntegration(slug: string) {
  const qc = useQueryClient();
  return useMutation<unknown, ApiError, void>({
    mutationFn: () => askApi.deleteTeams(slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: askKeys.teams(slug) }),
  });
}
