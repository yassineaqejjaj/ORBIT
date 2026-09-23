"use client";

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import { Command } from "cmdk";
import { ArrowRight, FolderKanban, LayoutGrid, Loader2, LogOut, Moon, Plus, Search, SearchX, Sun } from "lucide-react";

import { SourceKindIcon } from "@/components/domain/source-kind-icon";
import { PROJECT_NAV, projectHref } from "@/components/layout/nav";
import { useShell } from "@/components/layout/shell-context";
import { useTheme } from "@/components/providers/theme-provider";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/kbd";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useHotkey } from "@/hooks/use-hotkey";
import { errorMessage } from "@/lib/api/client";
import { useLogout, useProject, useProjects, useSearch } from "@/lib/api/hooks";
import type { SearchHit } from "@/lib/api/types";
import { getMeta, SOURCE_KIND_META } from "@/lib/enums";
import { formatScore, truncate } from "@/lib/format";
import { cn, normalizeText } from "@/lib/utils";

const MIN_QUERY = 2;

function matches(query: string, ...fields: Array<string | undefined>): boolean {
  const q = normalizeText(query);
  if (!q) return true;
  return fields.some((f) => f && normalizeText(f).includes(q));
}

function escapeRegExp(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Highlights query terms (accent-sensitive, case-insensitive) in a snippet. */
function Highlight({ text, query }: { text: string; query: string }) {
  const terms = query
    .split(/\s+/)
    .map((t) => t.trim())
    .filter((t) => t.length >= 2)
    .map(escapeRegExp);
  if (terms.length === 0) return <>{text}</>;
  const re = new RegExp(`(${terms.join("|")})`, "gi");
  const parts = text.split(re);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="rounded-sm bg-brand/15 px-0.5 text-foreground dark:bg-brand/25">
            {part}
          </mark>
        ) : (
          <React.Fragment key={i}>{part}</React.Fragment>
        ),
      )}
    </>
  );
}

/** Centered snippet window around the first matched term. */
function snippet(text: string, query: string, max = 150): string {
  const clean = text.replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  const first = query.split(/\s+/).find((t) => t.length >= 2);
  const idx = first ? normalizeText(clean).indexOf(normalizeText(first)) : -1;
  if (idx < 0) return truncate(clean, max);
  const start = Math.max(0, idx - Math.floor(max / 3));
  const out = clean.slice(start, start + max);
  return `${start > 0 ? "…" : ""}${out}${start + max < clean.length ? "…" : ""}`;
}

const itemClass = cn(
  "group flex cursor-default select-none items-center gap-3 rounded-md px-2.5 py-2 text-[13px] text-foreground outline-none",
  "data-[selected=true]:bg-accent data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50",
  "[&_svg]:size-4 [&_svg]:shrink-0",
);

const groupClass = cn(
  "px-1.5 pb-1 [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1.5 [&_[cmdk-group-heading]]:pt-3",
  "[&_[cmdk-group-heading]]:text-[10.5px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase",
  "[&_[cmdk-group-heading]]:tracking-[0.08em] [&_[cmdk-group-heading]]:text-subtle-foreground",
);

function SearchResult({ hit, query, onSelect }: { hit: SearchHit; query: string; onSelect: () => void }) {
  const kind = getMeta(SOURCE_KIND_META, hit.source_kind);
  return (
    <Command.Item value={`hit-${hit.chunk_id}`} onSelect={onSelect} className={cn(itemClass, "items-start")}>
      <SourceKindIcon kind={hit.source_kind} chip size="sm" className="mt-0.5" />
      <div className="grid min-w-0 flex-1 gap-0.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate font-medium">{hit.document_title}</span>
          {hit.section ? <span className="truncate text-xs text-muted-foreground">· {hit.section}</span> : null}
        </div>
        <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
          <Highlight text={snippet(hit.text, query)} query={query} />
        </p>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1 pt-0.5">
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground" title="Score de pertinence hybride">
          {formatScore(hit.score)}
        </span>
        <span className="text-[10.5px] text-subtle-foreground">{kind.label}</span>
      </div>
    </Command.Item>
  );
}

/** Global ⌘K / Ctrl+K palette: hybrid search in the current project, navigation, projects, actions. */
export function CommandPalette() {
  const router = useRouter();
  const params = useParams<{ slug?: string }>();
  const slug = typeof params.slug === "string" ? params.slug : undefined;
  const { commandPaletteOpen: open, setCommandPaletteOpen: setOpen, openCreateProject } = useShell();
  const { resolvedTheme, setTheme } = useTheme();
  const logout = useLogout();

  const [query, setQuery] = React.useState("");
  const debounced = useDebouncedValue(query, 220);
  const searchEnabled = Boolean(slug) && debounced.trim().length >= MIN_QUERY;

  const project = useProject(slug);
  const projects = useProjects({ enabled: open });
  const search = useSearch(slug, debounced, 8, { enabled: open && searchEnabled });

  useHotkey("k", () => setOpen(!open), { mod: true });
  useHotkey("/", () => setOpen(true), { enabled: !open });

  React.useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const run = React.useCallback(
    (fn: () => void) => {
      setOpen(false);
      // Let the dialog close before navigating (focus restoration).
      window.setTimeout(fn, 0);
    },
    [setOpen],
  );

  const navItems = slug
    ? PROJECT_NAV.filter((item) => matches(query, item.label, item.description, ...(item.keywords ?? [])))
    : [];
  const projectItems = (projects.data ?? []).filter((p) => matches(query, p.name, p.slug, p.description ?? undefined)).slice(0, 6);

  const actions = [
    { id: "new-project", label: "Nouveau projet", icon: Plus, keywords: "créer projet", run: () => openCreateProject() },
    { id: "all-projects", label: "Tous les projets", icon: LayoutGrid, keywords: "liste projets", run: () => router.push("/projects") },
    {
      id: "theme",
      label: resolvedTheme === "dark" ? "Passer au thème clair" : "Passer au thème sombre",
      icon: resolvedTheme === "dark" ? Sun : Moon,
      keywords: "thème apparence clair sombre dark light",
      run: () => setTheme(resolvedTheme === "dark" ? "light" : "dark"),
    },
    { id: "logout", label: "Se déconnecter", icon: LogOut, keywords: "déconnexion logout", run: () => logout.mutate() },
  ].filter((a) => matches(query, a.label, a.keywords));

  const hits = searchEnabled ? (search.data ?? []) : [];
  const searching = searchEnabled && (search.isFetching || debounced !== query);
  const nothing =
    navItems.length === 0 && projectItems.length === 0 && actions.length === 0 && hits.length === 0 && !searching;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        hideClose
        size="lg"
        className="top-[12vh] translate-y-0 gap-0 overflow-hidden p-0 sm:top-[14vh]"
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <DialogTitle className="sr-only">Recherche et commandes</DialogTitle>
        <DialogDescription className="sr-only">
          Recherchez dans les sources du projet courant, naviguez entre les pages ou lancez une action.
        </DialogDescription>
        <Command shouldFilter={false} loop label="Recherche et commandes" className="flex max-h-[min(70vh,560px)] flex-col">
          <div className="flex items-center gap-2.5 border-b border-border px-4">
            {searching ? (
              <Loader2 className="size-4 shrink-0 animate-spin text-brand" aria-hidden />
            ) : (
              <Search className="size-4 shrink-0 text-subtle-foreground" aria-hidden />
            )}
            <Command.Input
              autoFocus
              value={query}
              onValueChange={setQuery}
              placeholder={
                slug
                  ? `Rechercher dans ${project.data?.name ?? "le projet"}, ou une page, une action…`
                  : "Rechercher un projet, une page ou une action…"
              }
              className="h-12 w-full min-w-0 bg-transparent text-sm text-foreground outline-none placeholder:text-subtle-foreground"
            />
            <Kbd className="hidden sm:inline-flex">Échap</Kbd>
          </div>

          <Command.List className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-1">
            {slug && query.trim().length > 0 && query.trim().length < MIN_QUERY ? (
              <p className="px-4 py-3 text-xs text-muted-foreground">
                Saisissez au moins {MIN_QUERY} caractères pour lancer la recherche hybride dans les sources.
              </p>
            ) : null}

            {searchEnabled ? (
              <Command.Group heading="Sources du projet" className={groupClass}>
                {search.isError ? (
                  <p className="px-2.5 py-2 text-xs text-destructive">{errorMessage(search.error)}</p>
                ) : hits.length === 0 && !searching ? (
                  <div className="flex items-center gap-2 px-2.5 py-2 text-xs text-muted-foreground">
                    <SearchX className="size-3.5" aria-hidden />
                    Aucun extrait accessible ne correspond à « {debounced.trim()} ».
                  </div>
                ) : hits.length === 0 ? (
                  <Command.Loading>
                    <p className="px-2.5 py-2 text-xs text-muted-foreground">Recherche hybride BM25 + k-NN en cours…</p>
                  </Command.Loading>
                ) : (
                  hits.map((hit) => (
                    <SearchResult
                      key={hit.chunk_id}
                      hit={hit}
                      query={debounced}
                      onSelect={() =>
                        run(() =>
                          router.push(
                            `${projectHref(slug as string, "sources")}/${encodeURIComponent(hit.document_id)}?chunk=${encodeURIComponent(hit.chunk_id)}`,
                          ),
                        )
                      }
                    />
                  ))
                )}
              </Command.Group>
            ) : null}

            {navItems.length > 0 ? (
              <Command.Group heading={project.data ? `Aller à — ${project.data.name}` : "Aller à"} className={groupClass}>
                {navItems.map((item) => (
                  <Command.Item
                    key={item.segment || "overview"}
                    value={`nav-${item.segment || "overview"}`}
                    onSelect={() => run(() => router.push(projectHref(slug as string, item.segment)))}
                    className={itemClass}
                  >
                    <item.icon className="text-muted-foreground" aria-hidden />
                    <span className="font-medium">{item.label}</span>
                    <span className="hidden truncate text-xs text-muted-foreground sm:inline">{item.description}</span>
                    <ArrowRight className="ml-auto opacity-0 group-data-[selected=true]:opacity-60" aria-hidden />
                  </Command.Item>
                ))}
              </Command.Group>
            ) : null}

            {projectItems.length > 0 ? (
              <Command.Group heading="Projets" className={groupClass}>
                {projectItems.map((p) => (
                  <Command.Item
                    key={p.id}
                    value={`project-${p.slug}`}
                    onSelect={() => run(() => router.push(projectHref(p.slug)))}
                    className={itemClass}
                  >
                    <FolderKanban className="text-muted-foreground" aria-hidden />
                    <span className="truncate font-medium">{p.name}</span>
                    <span className="truncate font-mono text-[11px] text-subtle-foreground">{p.slug}</span>
                    {p.slug === slug ? <span className="ml-auto text-[11px] text-brand">Projet actuel</span> : null}
                  </Command.Item>
                ))}
              </Command.Group>
            ) : null}

            {actions.length > 0 ? (
              <Command.Group heading="Actions" className={groupClass}>
                {actions.map((a) => (
                  <Command.Item key={a.id} value={`action-${a.id}`} onSelect={() => run(a.run)} className={itemClass}>
                    <a.icon className="text-muted-foreground" aria-hidden />
                    <span>{a.label}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            ) : null}

            {nothing ? (
              <div className="px-4 py-10 text-center text-sm text-muted-foreground">
                Aucun résultat pour « {query.trim()} ».
                {!slug ? <p className="mt-1 text-xs">Ouvrez un projet pour rechercher dans ses sources.</p> : null}
              </div>
            ) : null}
          </Command.List>

          <div className="flex items-center justify-between gap-3 border-t border-border bg-muted/40 px-4 py-2 text-[11px] text-subtle-foreground">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1">
                <Kbd>↑</Kbd>
                <Kbd>↓</Kbd> naviguer
              </span>
              <span className="flex items-center gap-1">
                <Kbd>↵</Kbd> ouvrir
              </span>
            </div>
            <span className="hidden sm:inline">
              {slug ? "Résultats filtrés selon vos droits (ACL, classification)" : "Recherche hybride BM25 + k-NN"}
            </span>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
