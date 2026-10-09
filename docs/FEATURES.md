# ORBIT — Fonctionnalités produit (branche `features`, base `main`)

Contrat des 5 fonctionnalités à fort impact utilisateur. Complète `ARCHITECTURE.md` / `API.md` (toujours valables).
UI en français, conventions existantes (UI kit, hooks TanStack Query, `{detail, code}` pour les erreurs, audit de chaque mutation,
gouvernance identique au moteur de contexte : ACL, habilitation, mémoire utilisateur privée, caviardage PII).

## Garde-fou LLM (commun F3/F4)

LLM **optionnel**. Deux fournisseurs : `ORBIT_LLM_PROVIDER=openai` (compatible OpenAI : vLLM, Ollama, LiteLLM — existant) ou
`anthropic` (Messages API native, `ORBIT_LLM_API_KEY`, `ORBIT_LLM_MODEL` défaut `claude-sonnet-5`). Nouveaux réglages :
`ORBIT_LLM_MAX_CLASSIFICATION` (défaut `1` : seuls C0/C1 partent vers un LLM **externe** ; `ORBIT_LLM_LOCAL=true` lève le plafond
pour un LLM auto-hébergé), `ORBIT_LLM_REDACT_PII` (défaut `true`). Tout contenu au-dessus du plafond est traité en mode
déterministe ; compteur Prometheus `orbit_llm_guardrail_skips_total{reason}`. Sans LLM, tout fonctionne (repli déterministe).

## F1 — Tri de la mémoire & arbitrage des contradictions (`/projects/{slug}/inbox`)

- `GET /projects/{slug}/inbox?kind=&min_confidence=&sort=impact|confidence|recent&page=` (editor) → `Page<InboxItem>` :
  `MemoryItem` `proposed` visibles + `impact` (nb de contextes où l'item a été candidat sur 30 j, depuis `context_decisions`),
  `would_be_included` (nb de fois exclu *uniquement* parce que non validé — à défaut : nb de candidatures), `similar` (doublon probable : id + titre + score).
- `POST /projects/{slug}/inbox/bulk` (editor) `{action: "validate"|"reject"|"merge", ids: uuid[], into_id?: uuid, reason?}` →
  `{processed, failed: {id, detail}[]}`. `reject` = statut `obsolete` + événement raison « Rejeté au tri ». `merge` = provenance
  copiée vers `into_id`, autres items `obsolete` (« Fusionné dans … »). Atomique par item, audit `memory.bulk`.
- `GET /projects/{slug}/conflicts?status=open|resolved` → `Conflict[]` : `{id (relation), a: MemoryItem+sources, b: MemoryItem+sources,
  detected_at, similarity, suggested_winner_id, rationale (FR : validé > proposé, plus récent, plus fiable), status, resolution?}`.
- `POST /projects/{slug}/conflicts/{id}/resolve` `{winner_id, reason?}` → le perdant `superseded` par le gagnant (lifecycle existant),
  relation marquée résolue (`detail`), événements + audit `memory.conflict_resolved`. `POST …/dismiss` (pas une vraie contradiction).
- UI : page « Tri de la mémoire » avec onglets *Propositions* (liste triable, sélection multiple, barre d'actions groupées,
  raccourcis clavier `j/k` naviguer, `v` valider, `r` rejeter, `x` sélectionner, `m` fusionner, aperçu latéral avec provenance)
  et *Contradictions* (vue côte à côte : contenu, sources, dates, statut, confiance ; « Garder celle-ci » / « Pas une contradiction »).
  Badge de compteur dans la navigation. La Vue projet relie l'alerte « contradiction » à cet écran.

## F2 — Fil des changements, abonnements & webhooks (`/projects/{slug}/changes`)

- Table `change_events` (migration `f001`) alimentée **à l'écriture** (hook dans `services/audit.record` ou appels explicites) pour :
  `memory.validated|superseded|obsoleted|forgotten|conflict_detected|conflict_resolved`, `memory.created` (décisions/contraintes),
  `document.ingested|new_version|forgotten|stale` (périmé détecté par maintenance), `snapshot.created`, `connector.synced` (F5).
  Champs : `id, project_id, type, title, summary (FR), target_type, target_id, classification, acl_principals, actor_label, created_at, data jsonb`.
- `GET /projects/{slug}/changes?since=&types=&page=` → `Page<ChangeEvent>` (filtré par droits) ;
  `GET /projects/{slug}/changes/since-snapshot?name=&version=` → changements depuis la création d'une version de snapshot
  + liste des items du snapshot devenus remplacés/oubliés/périmés (« ce snapshot n'est plus à jour »).
- Abonnements : `GET/PUT /projects/{slug}/subscriptions/me` `{digest: "off"|"daily"|"weekly", types: string[]}` ;
  digest e-mail envoyé par le worker si `ORBIT_SMTP_HOST/PORT/USER/PASSWORD/FROM` configurés (sinon digest consultable dans l'UI :
  `GET /projects/{slug}/changes/digest?period=day|week`).
- Webhooks (owner) : `GET/POST /projects/{slug}/webhooks` `{url (https obligatoire hors dev), types[], description}` → secret affiché une fois ;
  `PATCH/DELETE …/{id}`, `POST …/{id}/test`, `GET …/{id}/deliveries`. Livraison par la file de jobs (`kind=webhook`, retries exponentiels,
  désactivation après 20 échecs), en-têtes `X-Orbit-Event`, `X-Orbit-Delivery`, `X-Orbit-Signature: sha256=<HMAC(secret, body)>`, timeout 10 s,
  **anti-SSRF** (refus IP privées/loopback/link-local après résolution DNS, sauf `ORBIT_ENV=development`). Payload : `ChangeEvent` caviardé
  au niveau `project:*` (pas de contenu C2+ ni restreint ACL — seulement type/titre générique/ids).
- UI : timeline groupée par jour, filtres par type, encart « Depuis le snapshot … » (sélecteur), réglages d'abonnement,
  gestion des webhooks dans Paramètres (onglet *Webhooks*).

### F2 bis — Événements de contexte en direct

- `context.served` : émis après persistance d'une requête de contexte (REST, MCP, « Demander à ORBIT » ; jamais pour les
  runs d'évaluation). `data` = identifiants et compteurs uniquement (`request_id`, `trace_id`, `agent_id/name`, `on_behalf_of`
  — jamais renvoyé par l'API —, `intent`, `included_count`, `excluded_count`, `tokens_used`, `token_budget`, `latency_ms`,
  `sufficiency`, `snapshot`, `max_classification`, `count`) ; **jamais** la tâche, les extraits ni les titres. Classification de
  l'événement = max des éléments servis (masqué au-delà de l'habilitation). Fusion par demandeur sur
  `ORBIT_CONTEXT_EVENTS_COALESCE_SECONDS` (compteur `count`). Webhooks : opt-in (un webhook sans type ne le reçoit pas), absent du digest
  sauf s'il est choisi dans l'abonnement.
- `GET /projects/{slug}/events/stream` (SSE, cookie ou Bearer, rôle lecteur) : `context.served`, `ingestion.updated`,
  `memory.changed`, `snapshot.created` (identifiants seulement), `degraded`, `reconnect` ; heartbeat 15 s, `Last-Event-ID`,
  diffusion Valkey pub/sub publiée après commit, filtrage par habilitation/ACL de l'abonné. L'interface se replie sur un polling de 10 s.

## F3 — Extraction de mémoire assistée par LLM

- `app/memory/llm_extraction.py` : prompt structuré → JSON validé (pydantic) de « fiches » `{kind, title, statement, decided_by?, decided_at?,
  rationale?, confidence (0–1), confidence_reason, source_quote}` ; la citation doit être une sous-chaîne (normalisée) du fragment, sinon rejet.
  Fusion avec l'extraction à règles (dédoublonnage existant) ; marquage `tags += ["extraction-llm"]`, champs de fiche dans `MemoryItem`
  (`rationale`, `decided_by`, `confidence_reason` — colonnes nullable, migration `f002`) affichés dans le détail mémoire et le tri.
- Garde-fou (voir plus haut), coût en tokens enregistré (étape de job `extract_memory` : `llm_calls, llm_tokens, skipped_guardrail`).
- Tests avec un faux serveur LLM (httpx MockTransport) : JSON valide, JSON invalide, citation hallucinée rejetée, plafond de classification.

## F4 — « Demander à ORBIT » (+ Teams)

- `POST /projects/{slug}/ask` (viewer, agent avec scope existant) `{question, conversation_id?, scopes?, token_budget? (défaut 3000)}` →
  `{answer (markdown avec [S1]…), citations: ContextItem[], confidence: "high"|"medium"|"low", follow_ups: string[], request_id, conversation_id, mode: "llm"|"extractive"}`.
  Utilise **le moteur de contexte existant** (`assemble_context`, même gouvernance, intent déduit) puis génère la réponse :
  LLM si autorisé par le garde-fou pour **tous** les items retenus (sinon items > plafond retirés de l'envoi et signalés), sinon réponse
  **extractive** (phrases les plus pertinentes, regroupées par décision/besoin/contrainte, citées). Jamais d'affirmation sans citation ;
  « Je ne trouve pas d'information validée sur ce point » si rien de pertinent. Conversations (table `ask_conversations` / `ask_messages`, migration `f002`),
  `GET /projects/{slug}/ask/conversations`, `GET …/{id}`, feedback 👍/👎 relié à `context_feedback`.
- UI : page chat (historique à gauche, réponse en markdown avec badges de citation cliquables → panneau source, suggestions de relance,
  questions d'exemple sur la démo : « Pourquoi a-t-on choisi une PWA ? », « Qu'a-t-on décidé sur l'authentification ? »).
- Teams : **webhook sortant Teams** (`POST /api/v1/integrations/teams/{project_slug}`) — vérification HMAC `Authorization: HMAC <base64>`
  avec le secret du webhook Teams (stocké chiffré, configuré par l'owner dans Paramètres → *Intégrations*), mapping de l'auteur Teams
  (`from.aadObjectId`/email) vers un utilisateur ORBIT membre (sinon réponse « compte non relié »), réponse au format message Teams
  (texte + liens vers l'app). Documentation pas à pas dans `docs/integrations/teams.md`.

## F5 — Connecteurs SharePoint, Confluence, Jira + assistant de démarrage (`/projects/{slug}/connectors`)

- Tables `connectors` (type, nom, config jsonb non secrète, `secret_ciphertext` (Fernet, clé `ORBIT_ENCRYPTION_KEY` — requise pour créer un connecteur),
  `schedule_minutes` défaut 60, `status`, `last_sync_at`, `last_error`, `cursor` jsonb, `source_id`), `connector_runs` (stats), migration `f003`.
- Connecteurs : **SharePoint/OneDrive** (Microsoft Graph, client credentials : tenant/client id/secret ; sites + bibliothèques choisis ;
  delta query pour l'incrémental ; fichiers → pipeline d'ingestion existant via `ingestion/service.ingest_content`), **Confluence** (Cloud/DC,
  email + API token ou PAT ; espaces choisis ; CQL `lastmodified >` ; pages → HTML → texte), **Jira** (Cloud/DC ; JQL ; tickets → documents
  `ticket` avec `external_id` = clé, commentaires inclus). Mapping des droits : par défaut `project:*` ; option « restreindre aux éditeurs » et
  classification par défaut par connecteur ; suppression côté source ⇒ oubli (tombstone) côté ORBIT.
- Synchronisation par le worker (job `kind=connector_sync`, planifiée par la maintenance), `POST …/{id}/sync` manuel, `POST …/test` (vérifie les identifiants
  sans ingérer), `GET …/{id}/runs`. Clients HTTP avec retries/backoff et respect du `Retry-After`. Tests avec MockTransport (pas d'appel réseau réel).
- **Assistant de démarrage** (projet vide ou depuis Connecteurs) : 1) choisir le type, 2) identifiants + test, 3) périmètre (sites/espaces/JQL)
  + classification/ACL, 4) première synchronisation avec progression en direct, 5) « Votre premier contexte » : lance l'Explorateur avec une tâche suggérée.
  La Vue projet d'un projet vide affiche « Connectez vos 2 premières sources ».

## F6 — Connecteurs MCP (`type = "mcp"`) + convertisseur MarkItDown

- Type de connecteur générique `mcp` (préréglage dans `config.preset`, migration `f004` : valeur ajoutée au CHECK du type) qui
  réutilise tout F5 (runs, planification, `POST …/test`, `…/sync`, événements de changement, audit, classification/ACL par défaut).
  Préréglages (`app/connectors/mcp/presets.py`, versions épinglées, détail et identifiants : `docs/integrations/mcp-servers.md`) :
  **Confluence & Jira** (mcp-atlassian), **Microsoft 365** (ms-365-mcp-server : SharePoint/OneDrive, Outlook, Teams),
  **Google Workspace** (workspace-mcp : Drive/Docs/Sheets, Gmail en option), **Slack** (slack-mcp-server), **GitHub** (serveur
  officiel distant ou binaire local), **Linear** (serveur distant officiel), **Obsidian** (mcp-obsidian + Local REST API) et un
  serveur **personnalisé** (ressources MCP) réservé aux administrateurs de la plateforme si `ORBIT_MCP_ALLOW_CUSTOM=true`.
- `GET /connectors/types` liste chaque préréglage (`via_mcp`, icône, description, champs `secret`/`connection`/`scope` avec
  libellés FR, aide « obtenir les identifiants », lien doc, outils requis). Secret = objet JSON des champs secrets, chiffré
  Fernet, indice masqué. Test = `initialize` + `list_tools` (outils requis présents) + un appel léger authentifié ; la réponse
  inclut `tools` (outils découverts).
- Client MCP (`app/connectors/mcp/client.py`, SDK 2.2) : stdio (commandes des préréglages uniquement, environnement minimal +
  secrets du connecteur, `HOME` temporaire) ou HTTP streamable (Bearer) ; délai par appel `ORBIT_MCP_TIMEOUT_SECONDS` avec arrêt
  du processus, `stderr` joint aux erreurs après caviardage. Limites `ORBIT_MCP_MAX_ITEMS`, `ORBIT_MCP_MAX_CONTENT_BYTES`,
  `ORBIT_MCP_SYNC_TIMEOUT_SECONDS`. URL saisies (Atlassian, Obsidian, serveur personnalisé) soumises à l'anti-SSRF.
- Incrémental : curseur par flux et par élément de périmètre (date de mise à jour max) quand l'outil filtre ou trie, sinon
  relecture + déduplication par empreinte ; suppressions détectées seulement sur les listings complets (Obsidian, docs GitHub,
  ressources) ou via le delta Graph, jamais sur un passage tronqué ou après changement de périmètre.
- **MarkItDown** (`app/ingestion/extractors/markitdown.py`) : extracteur de repli pour pptx, xlsx, xls, msg, eml, epub, odt/ods/odp,
  rtf, images via `markitdown-mcp` (`convert_to_markdown` sur un `file://` temporaire), `ORBIT_MARKITDOWN_MCP=auto|off`, motif FR
  si indisponible, étape `extract` « converti via MarkItDown (MCP) ».
- Images Docker : Node.js 24 et serveurs MCP épinglés installés au build (pas de téléchargement à l'exécution), utilisateur non-root.
- UI : préréglages « Via MCP » dans l'assistant (champs dynamiques, aide identifiants, outils découverts au test, canaux Slack
  proposés), badge « MCP » sur la liste et la fiche, édition des champs du préréglage.
- Sécurité/flux : les serveurs stdio s'exécutent dans le conteneur ORBIT avec les identifiants du connecteur ; un serveur distant
  (GitHub distant, Linear) fait transiter les données par l'éditeur ; utilisez des comptes de service en lecture seule et relevez
  la classification par défaut (C2/C3) pour les contenus sensibles.

## Migrations & fichiers

Chaîne : `0001` → `f001` (F1/F2 : `change_events`, `subscriptions`, `webhooks`, `webhook_deliveries`, statut relation résolue)
→ `f002` (F3/F4 : colonnes de fiche mémoire, `ask_conversations`, `ask_messages`, `integrations`) → `f003` (F5 : `connectors`, `connector_runs`) → `f004` (F6 : type de connecteur `mcp`).
Routeurs pré-enregistrés : `api/{inbox,feed,webhooks,ask,teams,connectors}.py`. Modèles : `models/{features_feed,features_ask,connector}.py`.
Pages pré-créées : `projects/[slug]/{inbox,changes,ask,connectors}/page.tsx` ; navigation déjà ajoutée (`components/layout/nav.ts`).
Le seed démo doit continuer de fonctionner et peut être enrichi (ex. 1 conflit ouvert, quelques changements, une conversation d'exemple).
