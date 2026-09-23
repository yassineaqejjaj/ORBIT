"use client";

import * as React from "react";
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { toast } from "sonner";

import { errorMessage, isApiError } from "@/lib/api/client";

declare module "@tanstack/react-query" {
  interface Register {
    mutationMeta: {
      /** Do not show the global error toast (the caller renders the error inline). */
      silentError?: boolean;
      /** Custom success toast message. */
      successMessage?: string;
    };
    queryMeta: {
      /** Show a toast when this query fails (default: errors are rendered inline). */
      toastError?: boolean;
    };
  }
}

const NO_RETRY_STATUSES = new Set([400, 401, 403, 404, 409, 422]);

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (query.meta?.toastError && !(isApiError(error) && error.isUnauthorized)) {
          toast.error(errorMessage(error));
        }
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _vars, _ctx, mutation) => {
        if (mutation.meta?.silentError) return;
        if (isApiError(error) && error.isUnauthorized) return; // redirecting to /login
        toast.error(errorMessage(error));
      },
      onSuccess: (_data, _vars, _ctx, mutation) => {
        if (mutation.meta?.successMessage) toast.success(mutation.meta.successMessage);
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: true,
        retry: (failureCount, error) => {
          if (isApiError(error) && (NO_RETRY_STATUSES.has(error.status) || error.isNetwork)) return false;
          return failureCount < 2;
        },
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
      },
      mutations: {
        retry: false,
      },
    },
  });
}

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = React.useState(makeQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
