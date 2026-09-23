# ORBIT — Web

Interface web d'ORBIT (plateforme de contexte et de mémoire pour agents IA).
Next.js 15 (App Router) · React 19 · TypeScript strict · Tailwind CSS v4 · Radix UI · TanStack Query v5 · Recharts · lucide-react.

## Démarrage

```bash
npm ci
npm run dev          # http://localhost:3000 — proxy /api/* et /mcp/* vers ORBIT_API_URL (défaut http://localhost:8000)
npm run typecheck    # tsc --noEmit
npm run lint         # eslint (config next/core-web-vitals + next/typescript), 0 warning toléré
npm run build        # build de production (output standalone)
npm start            # sert le build
```

## Backend et proxy (`ORBIT_API_URL`)

Le navigateur appelle toujours l'API en same-origin (`/api/v1/...`, `credentials: "include"`, cookie `orbit_session`).
`next.config.ts` déclare les rewrites :

| Source | Destination |
|---|---|
| `/api/:path*` | `${ORBIT_API_URL}/api/:path*` |
| `/mcp`, `/mcp/:path*` | `${ORBIT_API_URL}/mcp/...` |

**Important :** Next.js évalue les rewrites **au build** (ils sont figés dans `.next/routes-manifest.json`).
Changer `ORBIT_API_URL` sur une image déjà construite n'a aucun effet sur le proxy. L'URL est donc un argument de build :

```bash
docker build -t orbit-web ./frontend                                        # défaut : http://api:8000 (service compose)
docker build --build-arg ORBIT_API_URL=https://orbit-api.interne -t orbit-web ./frontend
```

L'image finale (`node:22-alpine`, utilisateur non-root `nextjs`, port 3000) sert `server.js` (output standalone) ;
sonde de vie : `GET /healthz`.

## Organisation

```
src/
  app/
    (auth)/login/            page de connexion (redirige vers ?next= ou /projects)
    (app)/layout.tsx         shell authentifié : garde (useMe), sidebar, header, palette ⌘K
    (app)/projects/          liste des projets + création
    (app)/projects/[slug]/   layout projet (CurrentProjectProvider) + pages par section
    healthz/route.ts         sonde de vie du conteneur
  components/
    ui/                      kit UI (Radix + Tailwind)
    domain/                  atomes métier (classification, codes de raison, statuts…)
    layout/                  sidebar, header, breadcrumb, palette de commandes, navigation
    projects/                carte projet, dialogue de création
    brand/                   logo ORBIT (SVG), illustration de connexion
    auth/require-role.tsx    <RequireRole min="editor">
  hooks/                     useCurrentProject, useDebouncedValue, useHotkey, useMediaQuery
  lib/
    api/types.ts             types du contrat docs/API.md (noms identiques)
    api/client.ts            fetch typé, ApiError, redirection 401 → /login?next=
    api/endpoints.ts         une fonction par endpoint
    api/query-keys.ts        fabrique de clés TanStack Query
    api/hooks.ts             hooks de requêtes et de mutations (invalidation incluse)
    enums.ts                 enums d'ARCHITECTURE §4 + libellés FR, tons, icônes
    format.ts                formatteurs FR (dates, durées, nombres, tokens, €, octets)
    tones.ts                 classes Tailwind par ton + palette graphique
```

## Conventions

- Textes d'interface et messages d'erreur en français ; identifiants et commentaires en anglais.
- Données serveur uniquement via les hooks de `@/lib/api/hooks` ; toutes les clés passent par `queryKeys`.
  Les erreurs de mutation sont notifiées globalement (toast) sauf `meta: { silentError: true }`.
- Contexte projet : `useCurrentProject()` → `{ project, slug, role, hasRole, canEdit, isOwner }` ;
  masquer une action : `<RequireRole min="editor">…</RequireRole>` (l'API applique les droits côté serveur).
- Afficher `<ClassificationBanner level={…} />` dès qu'un contenu C2/C3 est affiché, ingéré ou servi.
- Breadcrumb d'un élément dynamique : `useBreadcrumbLabel(documentId, document.title)`.
- Thèmes clair/sombre via variables CSS (`src/app/globals.css`), classe `dark` sur `<html>`.
