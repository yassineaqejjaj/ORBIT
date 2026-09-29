"use client";

import * as React from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

export type UrlParamValue = string | number | null | undefined;

/**
 * Reads and updates query-string state (tabs, filters, pagination) without adding history entries.
 * Empty values (`null`, `undefined`, `""`) remove the key so URLs stay short and shareable.
 */
export function useUrlParams() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const set = React.useCallback(
    (updates: Record<string, UrlParamValue>) => {
      const next = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(updates)) {
        if (value === null || value === undefined || value === "") next.delete(key);
        else next.set(key, String(value));
      }
      const query = next.toString();
      const current = searchParams.toString();
      if (query === current) return;
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams],
  );

  const get = React.useCallback((key: string): string | null => searchParams.get(key), [searchParams]);

  return { params: searchParams, get, set };
}

/** Parses a positive integer query param (page numbers…), falling back to `fallback`. */
export function parsePositiveInt(value: string | null, fallback = 1): number {
  if (!value) return fallback;
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n >= 1 ? n : fallback;
}
