# Design system — NOVA appliqué à ORBIT

ORBIT adopte le **design system NOVA** (ci-dessous, texte de référence inchangé) pour une identité commune au
programme. Ce qui suit précise comment il se traduit dans ORBIT ; en cas de doute, la référence NOVA prime pour le
visuel, l’architecture d’information d’ORBIT prime pour la navigation.

## Adaptation à ORBIT

| Sujet NOVA | Dans ORBIT |
|---|---|
| Accent « Red Poppy » #F8485E | Remplace le turquoise partout : actions principales, focus, état actif, badges d’action, liens. Le dégradé du logo « orbit » (corail → indigo) reste réservé à la marque (logo, icône). |
| Tokens sémantiques | Les noms existants (`--background`, `--card`, `--primary`, `--muted`…) sont conservés et alimentés par les valeurs NOVA ; les noms NOVA (`--surface-2`, `--surface-3`, `--text-subtle`, `--accent-soft`, `--glow`…) sont ajoutés. Aucune valeur hexadécimale dans les composants. |
| Groupes de navigation NOVA (Today, Goals…) | Non applicables : ORBIT garde ses groupes (Vue d’ensemble · Données · Contexte · Qualité · Suivi · Administration) et le bouton « Demander à ORBIT ». Le **gabarit** de la barre latérale NOVA s’applique : 224 px déplié / 64 px replié, ⌘\, état mémorisé, infobulles en mode replié, séparateurs fins à la place des titres de groupe. |
| Orbe NOVA (élément vivant) | Remplacé par l’**anneau « o » d’ORBIT** comme élément de présence : pastille dans la barre latérale (« ORBIT est opérationnel » / « Ingestion en cours… » / « 12 éléments à revoir »), états repos (respiration lente), travail (ingestion ou synchronisation en cours), attente (éléments à revoir). Pas d’orbe NOVA dans ORBIT. |
| Barre d’onglets mobile (5 entrées) | Vue d’ensemble, Sources, Mémoire, Contexte, Revue mémoire (avec compteur) ; le menu du haut ouvre toujours le tiroir complet. |
| Composer de la page d’accueil | S’applique à « Demander à ORBIT » (grande carte, rayon 26, bouton d’envoi rond corail) et au compositeur de tâche de l’Explorateur de contexte. |
| Couleurs d’identité des agents | Par type d’agent ORBIT : produit #F8485E, design #A78BFA, engineering #38BDF8, research #14B8A6, custom #22C55E (validation) ; #F59E0B réservé « projet ». |
| Confiance et citations | Niveaux élevé / moyen / faible (déjà en place sur les décisions) ; citations [S1] en pastilles reliées à la source. |
| Typographie | Geist Sans (ss01, cv11) pour l’interface, Geist Mono pour le code ; **Montserrat** pour la connexion. La landing page (bundle statique) n’est pas modifiée. |
| Classification C0–C3 | Sémantique conservée : C2 = warning, C3 = danger, bandeaux et badges inchangés dans leur sens. |
| Graphiques | Palette catégorielle harmonisée avec l’accent corail, contrastes AA vérifiés en clair et en sombre. |

---

# Référence : NOVA Design System

You are designing for **NOVA**, a personal AI product agent: a permanent member of the product team.
It plans goals, runs missions with specialist sub-agents and asks for decisions. The interface must
feel **calm, warm, precise and trustworthy**: a quiet workspace where one living element (the NOVA orb)
shows that the agent is present. There is no visual noise. Every surface earns its place.

## Personality
- Warm minimalism: off-white canvas, white cards, one coral accent used sparingly.
- Editorial and confident: large tight headings, small precise UI text, generous whitespace.
- Alive but never loud: motion only signals presence or progress (orb, shimmer on live activity).
- Transparent: show who did what (agent identity colors), how confident NOVA is, and where content
  comes from (citations [S1]).

## Color tokens
Use semantic tokens only, never raw hex values in components. Dark mode is a `.dark` class on <html>.

| Token          | Light                          | Dark                            | Usage                             |
|----------------|--------------------------------|---------------------------------|-----------------------------------|
| background     | #FAF8F7                        | #0D0C0D                         | App canvas                        |
| surface        | #FFFFFF                        | #151314                         | Cards, sidebar, composer          |
| surface-2      | #F6F2F1                        | #1B1819                         | Inputs, hover, active nav item    |
| surface-3      | #EFE9E7                        | #231F20                         | Pressed, avatars, skeletons, code |
| border         | rgb(30 20 18 / 0.07)           | rgb(255 255 255 / 0.07)         | Default 1px hairlines             |
| border-strong  | rgb(30 20 18 / 0.12)           | rgb(255 255 255 / 0.12)         | Outline buttons, tooltips         |
| text           | #191716                        | #F1EEED                         | Primary text                      |
| text-muted     | #5F5856                        | #AAA3A1                         | Secondary text, inactive nav      |
| text-subtle    | #9A918E                        | #736C6A                         | Meta, hints, group labels, icons  |
| accent         | #F8485E "Red Poppy"            | #F8485E                         | Primary actions, focus, badges    |
| accent-strong  | #E8344B                        | #FF6276                         | Primary hover                     |
| accent-soft    | #FEEDEF                        | rgb(248 72 94 / 0.14)           | Tinted chips, selection           |
| accent-fg      | #FFFFFF                        | #FFFFFF                         | Text on accent                    |
| glow           | rgb(248 72 94 / 0.30)          | rgb(248 72 94 / 0.22)           | Orb halo, hero radial             |
| success        | #16A34A                        | oklch(0.76 0.13 155)            | Done, approved, "Always"          |
| warning        | #D97706                        | oklch(0.80 0.13 75)             | Waiting, "Ask", reservations      |
| danger         | #DC2626                        | oklch(0.68 0.17 25)             | Failed, "Never", destructive      |

Status tints: background at 12–15 % of the status color, text in the full color
(e.g. success/12 + success). Text selection uses accent-soft.

## Typography
- UI: **Geist Sans**, with font-feature-settings "ss01", "cv11" and antialiasing. Code and shortcuts: **Geist Mono**.
- Brand pages (landing, sign-in, logout, legal): **Montserrat** 400/500/600/700.
- Scale (px): 10.5 · 11 · 11.5 · 12 · 12.5 · **13 (default UI)** · 13.5 · 14 (nav, body) · 15 (card titles)
  · 16 (lead) · 17 · 24 (step titles) · 28 (page titles) · 32–40 (home hero).
- Headings: font-weight 600, letter-spacing tight, line-height 1.1 for the hero.
- Group labels: 11px, semibold, UPPERCASE, wider tracking, text-subtle.
- Sentence case everywhere. French copy uses typographic apostrophes (’), guillemets « » and a
  space before ":" "?" "!".

## Shape, depth, spacing
- Radii: 8 (small), 10 (buttons, inputs, nav items), 12 (menus, pills), 14 (cards), 16–18 (panels),
  22 (feature cards), 26–28 (hero, composer). Pills and avatars are fully round.
- Shadow "panel", light: `0 1px 2px rgb(30 20 18/.04), 0 10px 30px -12px rgb(30 20 18/.12)`.
  Dark: `inset 0 1px 0 rgb(255 255 255/.03), 0 12px 32px -12px rgb(0 0 0/.6)`.
- Elevated cards: `0 18px 50px -30px rgb(0 0 0/.3)` plus a 1px ring in the border color.
- Borders are 1px hairlines in the border token, never heavier. Thin, discreet scrollbars.
- Spacing on a 4px grid. Content column: max-width 920px (or 1180px for wide pages), padding 20–32px
  horizontal and 32–40px vertical.

## Layout
- Desktop: sticky left sidebar, then content.
  - **Sidebar, expanded (224px):** NOVA logo on the left, collapse button on the right of the header,
    presence pill, then nav groups.
  - **Sidebar, collapsed (64px):** NOVA mark, expand button, presence orb, then icons only with the
    labels in tooltips on the right. Thin separators replace the group labels. The state is
    remembered, and ⌘\ toggles it.
- Nav groups:
  - **NOVA:** Today · Goals · Missions · Tasks · Inbox
  - **Workspace:** Projects · Artifacts · Knowledge
  - **Automation:** Skills · Routines · Product team
  - **Activity:** Timeline
- Settings and the account menu (avatar, name, role) sit at the bottom.
- Nav item: 36px high, 18px lucide icon, 14px label. Active: surface-2 background, medium weight,
  primary text. Inactive: text-muted, hover surface-2 at 70 %. The Inbox count is a coral pill.
- Top bar: a search pill ("Search ⌘K") on surface-2/80, fully rounded.
- Mobile: no sidebar. A fixed bottom tab bar (64px, blurred surface/95) with 5 entries:
  Today, Goals, Inbox, Tasks, Artifacts. The active entry is in accent.

## Components
- **Button** (radius 10, 14px medium, 16px icons, gap 8):
  - primary = accent background with white text (hover accent-strong);
  - secondary = surface-2 with a border (hover surface-3);
  - ghost = text-muted (hover surface-2);
  - outline = border-strong;
  - danger = danger/15 background with danger text;
  - link = accent with an underline on hover.
  - Sizes: sm 32px, md 36px, lg 44px, icon 32×32.
  - Focus: a 2px ring in accent at 50 %. Disabled: 50 % opacity.
- **Input / Textarea:** 36px high, radius 10, surface-2 background with a border, placeholder in
  text-subtle, focus ring accent/40.
- **Card:** radius 14, surface background, hairline border, panel shadow. Padding 20px for content cards.
- **Badge:** radius 6, 11px medium. Tones: neutral (surface-3 / muted), accent (accent-soft / accent),
  success, warning, danger.
- **Kbd:** mono 10px on surface-2 with a border, radius 6.
- **Tooltip:** surface-3 background, border-strong, 12px text, 250ms delay.
- **Segmented choice** (e.g. Always / Ask / Never): a rounded-full track with pills. The active pill
  takes its status tint: success, warning or danger.
- **Composer:** the hero of the home page. A large surface card (radius 26) with a multiline prompt
  "Ask NOVA what you want to achieve", attachment chips (File, ORBIT source, Artifact, Skill), a
  project selector, and a round coral send button.
- **Home hero** (radius 28): background
  `radial-gradient(120% 140% at 85% 10%, rgb(248 72 94/.16), transparent 55%)` over
  `linear-gradient(180deg, surface, surface-2)`. 32–40px greeting, a one-line status, and the orb on the right.
- **Skeletons:** surface-3 with a pulse.

## The NOVA orb (signature element)
- A glossy, softly animated sphere in coral (devoteam), with a glow halo in rgb(248 72 94).
- **States:** idle (slow breathing), working (faster, brighter), waiting (gentle pulse, needs the user).
- **Placements:** home hero (large), presence pill in the sidebar (26px plus the status line
  "NOVA is available" / "Working on …"), the "Today" nav icon, and the composer.
- **User-selectable palettes** (hue shifts of the same artwork): Coral (default), Rose, Violet, Ocean,
  Emerald, Amber, Graphite.

## Agents (identity colors)
Each sub-agent has a color used for its avatar, its name and its timeline rail.
- **Avatar:** its icon on a disc filled with `color-mix(color 14 %)`, with a border of `color-mix(color 35 %)`.
- **Colors:**
  - Product #F8485E (coral)
  - Project #F59E0B (amber)
  - Design #A78BFA (violet)
  - Engineering #38BDF8 (sky)
  - Research #14B8A6 (teal)
  - Validation #22C55E (green)
- **Orchestration view ("NOVA Core orchestrates the agents"):**
  - phase cards: Planning → Decomposition → Assignment & routing → Monitoring & supervision;
  - a vertical rail of agent steps, each with a check / spinner / waiting status, its elapsed time,
    sub-steps with counts, and an inline note from the Validation agent.

## Feedback and trust
- Confidence badge: a high / medium / low score from the Validation agent (and FORGE when known),
  capped at "medium" when there are no sources.
- Citations appear inline as [S1] chips that link to the source.
- Statuses: Queued, Working (accent spinner), Waiting for you (warning), Done (success check),
  Failed (danger), Delivered with reservations (warning).
- Toasts (sonner): short, sentence case, no exclamation marks.

## Motion
- Subtle: 150–200ms color and width transitions, gentle hover scale (1.03) on the orb button.
- Live activity: a shimmer gradient sweeps across the text (2.4s loop) while an agent works.
- Always honor prefers-reduced-motion: no shimmer, near-zero durations.

## Iconography and voice
- Icons: lucide, 1.5–2px stroke. 18px in the nav, 16px in buttons, 14px inline. Inactive icons use text-subtle.
- Voice: bilingual FR/EN, concise, action-oriented, the user's language. NOVA speaks as a teammate
  ("I'm ready when you are."), never as a tool. No jargon, no emojis in the UI.

## Accessibility
- Visible focus rings (accent), aria-labels on icon-only controls, labels kept for screen readers
  when visually hidden (collapsed sidebar), AA contrast on both themes, full keyboard support
  (⌘K search, ⌘\ sidebar).
