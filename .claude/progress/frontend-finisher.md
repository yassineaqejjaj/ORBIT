# frontend-finisher progress
## Done
- Settings page: app/(app)/projects/[slug]/settings/page.tsx (Suspense) -> components/settings/settings-view.tsx
  tabs ?tab=project|members|agents|mcp|audit (matches existing deep links in overview/alerts-card/activity-timeline).
- components/settings/audit-panel.tsx (new): domain+verb filter (?action=), pagination (?page=), JSON details, loading/empty/error.
- Existing panels (project-settings, members, agents + key dialog, mcp) were already complete; wired in.
- Completeness pass: no UnderConstruction/placeholder left in project pages; all pages use real hooks.
- npm run typecheck: 0 errors; npm run lint: 0 errors/warnings; npm run build: success (all 15 routes).
## Next
- None. Optional: remove unused components/layout/under-construction.tsx (not in my ownership).
## Known issues
- API :8000 was not reachable at verification time: no live browser check done.
