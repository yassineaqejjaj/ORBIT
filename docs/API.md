# ORBIT — Contrat API REST v1

Base : `/api/v1`. JSON, `snake_case`, dates ISO 8601 UTC. Le frontend appelle `/api/v1/...` en same-origin
(Next.js réécrit `/api/*` vers le backend) avec `credentials: "include"`.

Erreurs : `{"detail": "message lisible en français", "code": "not_found|forbidden|validation_error|conflict|unauthorized"}`
avec le code HTTP adéquat (401, 403, 404, 409, 422).

Pagination : query `page` (1-based, défaut 1), `page_size` (défaut 25, max 100) → `Page<T> = {items: T[], total, page, page_size}`.

`{slug}` = slug du projet. Accès : membre du projet (ou admin), rôle minimal indiqué [viewer|editor|owner].
Les endpoints marqués **(agent)** acceptent aussi une clé API d'agent du projet.

---

## Types partagés

```ts
User        = { id, email, full_name, is_admin: bool, clearance: 0|1|2|3, avatar_color: string, created_at, onboarding_completed_at: datetime|null }
Member      = { user: User, role: Role, created_at }
Project     = { id, orion_project_id /* id commun ORION, immuable (= id) */, slug, name, description, settings: ProjectSettings, role: Role /* rôle de l'appelant */, created_at, updated_at }
ProjectSettings = { freshness_days: Record<SourceKind, number>, default_token_budget: number, min_relevance: number, short_term_ttl_hours: number }
ProjectSummary = Project & { stats: { sources: number, documents: number, memory_items: number, context_requests_7d: number } }

Agent       = { id, name, kind: AgentKind, description, clearance, api_key_prefix, active, created_at, last_used_at, role: "viewer"|"editor", expires_at: datetime|null, rotated_at: datetime|null }
AgentCreated = { agent: Agent, api_key: string /* affichée une seule fois */ }

Source      = { id, name, kind: SourceKind, description, default_classification, default_acl: string[], config: object,
                created_at, updated_at, last_ingested_at, counts: { documents, indexed, failed, processing } }

DocumentSummary = { id, source_id, source_name, source_kind, external_id, title, uri, mime_type, author,
                    classification, acl_principals: string[], tags: string[], status: DocumentStatus, status_reason,
                    current_version, pii_count, chunk_count, source_updated_at, created_at, updated_at }
DocumentVersion = { id, version, content_hash, size_bytes, created_at, char_count }
ChunkView   = { id, version, ordinal, text, text_redacted, token_count, section, pii: PiiEntity[], classification, status }
PiiEntity   = { type: "EMAIL"|"PHONE"|"IBAN"|"CARD"|"NIR"|"IP"|"PERSON", start, end, text? /* omis si l'appelant < editor */ }
Job         = { id, document_id, kind: JobKind, status: JobStatus, attempts, error, steps: JobStep[], created_at, started_at, finished_at }
JobStep     = { name: "extract"|"pii"|"classify"|"chunk"|"embed"|"index"|"extract_memory"|string, status: "ok"|"failed"|"skipped", duration_ms, detail }
DocumentDetail = DocumentSummary & { metadata: object, versions: DocumentVersion[], chunks: ChunkView[] /* version courante */,
                    jobs: Job[], memory_items: MemoryItem[] /* dérivés */, forgotten_at, forgotten_by }

MemoryItem  = { id, lineage_id, version, is_current, scope: MemoryScope, kind: MemoryKind, status: MemoryStatus,
                title, content, confidence, classification, acl_principals, tags,
                subject_user_id, session_id, expires_at, valid_from, valid_to,
                supersedes_id, superseded_by_id, created_by_type, created_by_id, created_by_label,
                provenance_count, created_at, updated_at }
Provenance  = { id, document_id, document_title, chunk_id, context_request_id, source_label, excerpt, created_at }
MemoryEvent = { id, memory_item_id, event: MemoryEventType, actor_type, actor_id, actor_label, reason, data, created_at }
Relation    = { id, rel_type: RelationType, direction: "out"|"in", other_type, other_id, other_title, confidence, detail, created_at }
MemoryDetail = { item: MemoryItem, provenance: Provenance[], history: MemoryEvent[], versions: MemoryItem[], relations: Relation[] }

AuditEvent  = { id, actor_type, actor_id, actor_label, action, target_type, target_id, summary, details, created_at }
```

---

## Auth & utilisateurs

| Méthode | Chemin | Corps / Query | Réponse |
|---|---|---|---|
| POST | `/auth/login` | `{email, password}` | `User` + cookie `orbit_session` |
| POST | `/auth/logout` | — | `204` |
| GET | `/auth/me` | — | `User` |
| POST | `/auth/me/onboarding/complete` | — | `User` (idempotent : termine ou passe la visite de bienvenue) |
| POST | `/auth/me/onboarding/restart` | — | `User` (`onboarding_completed_at` repasse à `null`) |
| GET | `/users` (admin) | `q?` | `User[]` |
| POST | `/users` (admin) | `{email, full_name, password, clearance, is_admin}` | `User` |
| PATCH | `/users/{id}` (admin) | `{full_name?, clearance?, is_admin?, password?}` | `User` |

## Projets, membres, agents

| Méthode | Chemin | Rôle | Corps / Query | Réponse |
|---|---|---|---|---|
| GET | `/projects` | — | — | `ProjectSummary[]` (projets de l'appelant ; tous pour admin) |
| POST | `/projects` | tout utilisateur | `{name, slug?, description?}` | `Project` (appelant owner) |
| GET | `/projects/{slug}` | viewer | — | `Project` |
| PATCH | `/projects/{slug}` | owner | `{name?, description?, settings?}` (merge partiel de settings) | `Project` |
| GET | `/projects/{slug}/overview` | viewer | — | `Overview` (cf. ci-dessous) |
| GET | `/projects/{slug}/members` | viewer | — | `Member[]` |
| POST | `/projects/{slug}/members` | owner | `{email, role}` | `Member` |
| PATCH | `/projects/{slug}/members/{user_id}` | owner | `{role}` | `Member` |
| DELETE | `/projects/{slug}/members/{user_id}` | owner | — | `204` (interdit de retirer le dernier owner → 409) |
| GET | `/projects/{slug}/agents` | viewer | — | `Agent[]` |
| POST | `/projects/{slug}/agents` | owner | `{name, kind, description?, clearance, role?: "viewer"\|"editor", expires_in_days?}` | `AgentCreated` |
| POST | `/projects/{slug}/agents/{id}/rotate` | owner | `{expires_in_days?}` (optionnel) | `AgentCreated` |
| DELETE | `/projects/{slug}/agents/{id}` | owner | — | `204` (révocation : `active=false`) |
| GET | `/agents/self` | **clé d'agent** | — | `AgentSelf` (identité de la clé appelante, hors projet) |

```ts
AgentSelf = { id, name, kind: AgentKind, description, clearance: 0|1|2|3,
              project: { id, slug, name },
              key: { prefix, status: "active", created_at, last_used_at: string|null } }
```

**Clés d'agent rattachées (ADR 001 §7, NOV-112).** Une clé `orb_…` appartient à un projet **et** à son espace (`workspace_id`, repris du
projet à la création), porte une habilitation **explicite** (`clearance`), un rôle explicite (`viewer` ou `editor`, jamais `owner` ;
`editor` par défaut, comme avant), une expiration facultative (`expires_in_days` ; une clé expirée répond `401`) et la date de sa
dernière rotation. **Rotation** : `POST …/rotate` génère un nouveau secret (l'ancien est refusé aussitôt), garde espace, projet, rôle
et habilitation, et renouvelle une clé expirée (avec `expires_in_days` ; sans corps l'expiration reste). L'audit nomme la clé
(`actor_type=agent`), jamais un utilisateur. Outil d'administration, sans aucun secret :
`python -m app.admin keys list [--workspace <uuid>] [--project <slug>] [--json]` (âge, dernière utilisation, statut
`active|expired|revoked|misplaced`) et `python -m app.admin keys revoke-misplaced [--dry-run]` (révoque les clés dont l'espace n'est
plus celui de leur projet).

`GET /agents/self` répond avec une clé d'agent seulement (`Authorization: Bearer orb_…` ou `X-Orbit-Key`) : `403` avec une
session utilisateur, `401` sans identifiants. Une clé révoquée, renouvelée ou inconnue reçoit `401` (« Clé d'agent révoquée » /
« invalide ») : `key.status` vaut donc toujours `active` quand la réponse est `200`. La clé complète et son empreinte ne sont jamais renvoyées.

```ts
Overview = {
  project: Project,
  stats: { sources, documents, documents_indexed, chunks, memory_items, validated_decisions, context_requests_7d,
           snapshots, pii_documents, restricted_documents /* C2+ */ },
  ingestion: { queued, running, failed, succeeded_24h },
  memory_by_status: Record<MemoryStatus, number>,
  memory_by_scope: Record<MemoryScope, number>,
  context: { requests_7d, p95_latency_ms, avg_tokens, avg_included, exclusion_rate },
  sources_by_kind: Record<SourceKind, number>,
  latest_decisions: MemoryItem[],      // 5 dernières décisions validées
  recent_activity: AuditEvent[],       // 15 derniers événements
  alerts: { level: "info"|"warning"|"critical", message }[]   // ex. jobs en échec, conflits non résolus, contenus C3
}
```

## Sources & documents

| Méthode | Chemin | Rôle | Corps / Query | Réponse |
|---|---|---|---|---|
| GET | `/projects/{slug}/sources` | viewer | — | `Source[]` |
| POST | `/projects/{slug}/sources` | editor | `{name, kind, description?, default_classification?, default_acl?, config?}` | `Source` |
| PATCH | `/projects/{slug}/sources/{id}` | editor | mêmes champs optionnels | `Source` |
| GET | `/projects/{slug}/documents` | viewer | `source_id?, status?, source_kind?, classification?, q?, page, page_size` | `Page<DocumentSummary>` |
| POST | `/projects/{slug}/documents/upload` | editor **(agent)** | multipart : `files[]`, `source_id?`, `classification?`, `acl_principals?` (CSV), `tags?` (CSV) | `DocumentSummary[]` (statut `pending`) |
| POST | `/projects/{slug}/documents/text` | editor **(agent)** | `TextDocumentIn` | `DocumentSummary` |
| POST | `/projects/{slug}/documents/meeting` | editor **(agent)** | multipart : `file` (transcription `.vtt`/`.srt`/`.docx`/`.txt`/`.md` ou audio si `ORBIT_TRANSCRIPTION_BASE_URL`), `title?`, `meeting_date?` (AAAA-MM-JJ), `participants?` (CSV), `source_id?`, `classification?`, `acl_principals?`, `tags?` — §F1 ; `DocumentDetail.metadata.meeting` = `{date, participants, speakers, turn_count, duration_seconds, turns[{speaker, start, end, text}]}` ; 422 si audio C2/C3 vers un service externe ou trop volumineux | `DocumentSummary` |
| POST | `/projects/{slug}/documents/import` | editor **(agent)** | multipart : `file` (JSON array ou CSV), `source_kind`, `source_id?` | `{created: number, updated: number, documents: DocumentSummary[]}` |
| GET | `/projects/{slug}/documents/{id}` | viewer | — | `DocumentDetail` (caviardé si pas d'accès → 404) |
| PATCH | `/projects/{slug}/documents/{id}` | editor | `{title?, classification?, acl_principals?, tags?}` | `DocumentSummary` (réindexation des métadonnées) |
| POST | `/projects/{slug}/documents/{id}/reprocess` | editor | — | `Job` |
| POST | `/projects/{slug}/documents/{id}/forget` | owner | `{reason}` | `DocumentSummary` (statut `forgotten`) |
| GET | `/projects/{slug}/documents/{id}/raw` | editor | — | fichier original |
| GET | `/projects/{slug}/jobs` | viewer | `status?, page` | `Page<Job & {document_title}>` |
| GET | `/projects/{slug}/search` | viewer | `q, limit=20` | `SearchHit[]` (hybride, **filtré** par les droits de l'appelant) |

```ts
TextDocumentIn = { source_id?: uuid, source_kind?: SourceKind /* si pas de source_id : source par défaut du type, créée à la volée */,
                   title, content, external_id?, uri?, author?, classification?, acl_principals?, tags?,
                   source_updated_at?, metadata? }
SearchHit = { chunk_id, document_id, document_title, source_kind, text, score, bm25, dense, section, source_updated_at }
```
Import JSON/CSV — colonnes reconnues : `id|external_id`, `title|summary|subject|name`, `content|description|body|text|notes`,
`author|reporter|owner`, `updated_at|date|created`, `status`, `priority`, `tags|labels`, `classification`, `url|uri`
(les autres colonnes vont dans `metadata`). Un ticket/compte CRM/feedback/trace = un document.

## Mémoire

| Méthode | Chemin | Rôle | Corps / Query | Réponse |
|---|---|---|---|---|
| GET | `/projects/{slug}/memory` | viewer | `scope?, kind?, status?, q?, include_history=false, as_of? (§D2 « tel que connu au »), page, page_size` | `Page<MemoryItem>` (versions courantes, filtrées par droits) |
| POST | `/projects/{slug}/memory` | editor **(agent)** | `MemoryIn` | `MemoryItem` (agent ⇒ statut `proposed` forcé) |
| GET | `/projects/{slug}/memory/{id}` | viewer | — | `MemoryDetail` |
| PATCH | `/projects/{slug}/memory/{id}` | editor | `{title?, content?, tags?, valid_to?, classification?, kind?, skill_meta?}` | `MemoryItem` (nouvelle version) |
| POST | `/projects/{slug}/memory/{id}/validate` | editor | `{reason?}` | `MemoryItem` |
| POST | `/projects/{slug}/memory/{id}/obsolete` | editor | `{reason}` | `MemoryItem` |
| POST | `/projects/{slug}/memory/{id}/supersede` | editor | `{by_id, reason?}` | `MemoryItem` (l'ancien) |
| POST | `/projects/{slug}/memory/{id}/restore` | editor | `{reason?}` | `MemoryItem` |
| POST | `/projects/{slug}/memory/{id}/forget` | owner (ou sujet pour scope `user`) | `{reason}` | `MemoryItem` |
| POST | `/projects/{slug}/memory/consolidate` | editor | — | `Job` |
| GET | `/projects/{slug}/memory/graph` | viewer | `limit=150` | `{nodes: {id,type,label,kind,status}[], edges: {source,target,rel_type,confidence?,detail?,method?}[]}` (nœuds `entity` §D2) |
| GET | `/projects/{slug}/memory/contradictions` | viewer | `limit=500` | `{clusters: {severity: critical\|review\|minor, suggested_keep, max_classification, items: {id,title,kind,status,classification,confidence,valid_from,excerpt}[], edges: {a,b,score?,method?,explanation?}[]}[], counts: {critical,review,minor}}` — contradictions entre éléments vivants (proposés ou validés) visibles par l'appelant ; une contradiction avec un élément qu'il ne peut pas voir n'est ni affichée ni comptée |
| GET | `/projects/{slug}/memory/as-of-diff` | viewer | `from` (requis), `to` (défaut : maintenant), `limit=1000` | `{date_from, date_to, added: KnownItem[], removed: {item, why: replaced\|obsolete\|expired\|forgotten\|unknown, replaced_by?}[], changed: {before, after}[], counts, max_classification}` — ce que le projet savait à `from` comparé à `to` (mémoire « telle que connue au », §D2), avec les droits de l'appelant ; `422` si `from` ≥ `to` |
| GET | `/projects/{slug}/memory/{id}/trail` | viewer | — | `{item_id, title, why: {kind,status,rationale?,decided_by?,confidence,confidence_reason?,valid_from}, chain: {id,title,status,version,valid_from,classification,role: replaced\|current\|replaced_by}[], timeline: {at,kind,label,detail,item_id?,document_id?,actor}[], max_classification}` — pourquoi cette décision : ce qu'elle a remplacé, ce qui l'a remplacée, ses sources et ses revues, du plus ancien au plus récent ; seuls les éléments visibles par l'appelant y figurent |
| GET | `/projects/{slug}/knowledge-gaps` | editor | `days=30` (1–180), `limit=30` | `{window_days, analysed_requests, gaps: {key,topic,requests,askers,first_seen,last_seen,avg_score,trend: rising\|steady\|fading,severity: critical\|recurring\|isolated,contributors: {user_id,label,items}[],requested}[]}` — sous-sujets que le contexte servi n'a pas couverts (verdict de suffisance `partial`/`insufficient`), regroupés par termes ; seul le sujet est exposé, jamais la question ; contributeurs tirés de la mémoire visible par l'appelant |
| POST | `/projects/{slug}/knowledge-gaps/request` | editor | `{topic}` | `MemoryItem` — ouvre une action « Documenter : … » proposée (revue mémoire) ; `409` si une demande existe déjà |
| POST | `/projects/{slug}/memory/reflect` | editor | `month?=AAAA-MM` (défaut : mois précédent) | `Job` (§D4 synthèse « ce qui a changé » proposée) |
| GET | `/projects/{slug}/skills` | viewer | — | `Skill[]` (§D1 procédures servies comme Agent Skills) |
| GET | `/projects/{slug}/skills/{name}` | viewer | — | `Skill & {skill_md}` (SKILL.md avec métadonnées) |
| GET | `/projects/{slug}/skills/{name}/download` | viewer | — | zip `<name>/SKILL.md` |
| GET / POST | `/projects/{slug}/entities` | viewer / editor | `{name, kind?, aliases?}` | `Entity[]` / `Entity` (§D2) |
| GET | `/projects/{slug}/entities/suggestions` | editor | — | `{a, b, score, reason}[]` (fusions suggérées) |
| POST | `/projects/{slug}/entities/{id}/merge` · `/unmerge` | editor | `{source_id, reason?}` · `{reason?}` | `Entity` (audités `entity.merge` / `entity.unmerge`) |

```ts
MemoryIn = { scope, kind, title, content, classification?, acl_principals?, tags?, subject_user_id?, session_id?,
             valid_from?, valid_to?, confidence?, supersedes_id?, status?: "proposed"|"validated",
             provenance?: { document_id?, chunk_id?, excerpt?, source_label? }[],
             skill_meta?: { name?, description?, task_types?: Intent[], agent_kinds?: AgentKind[] } }  // kind "procedure"
```

## Sessions (mémoire court terme) **(agent)**

| Méthode | Chemin | Rôle | Corps | Réponse |
|---|---|---|---|---|
| POST | `/projects/{slug}/sessions/{session_id}/turns` | editor | `{role: "user"|"agent"|"tool", content, agent_id?}` | `{session_id, turns: number, expires_at}` |
| GET | `/projects/{slug}/sessions/{session_id}` | viewer | — | `{session_id, turns: {role, content, at}[], expires_at, memory_items: MemoryItem[]}` |
| POST | `/projects/{slug}/sessions/{session_id}/close` | editor | — | `{summary: MemoryItem \| null}` (consolidation en `summary` projet) |
| GET | `/projects/{slug}/sessions` | viewer | — | `{session_id, turns, updated_at, expires_at}[]` |

## Contexte **(agent)**

`POST /projects/{slug}/context` — rôle viewer (humain) ou agent.

```ts
ContextRequestIn = {
  task: string,                          // requis
  intent?: Intent,                       // défaut : déduit
  agent_id?: uuid,                       // humain simulant un agent (Explorateur)
  on_behalf_of?: uuid,                   // défaut : appelant humain ; pour agent : membre du projet
  token_budget?: number,                 // défaut settings.default_token_budget (min 500, max 32000)
  scopes?: MemoryScope[],                // défaut ["short_term","project","user","long_term"]
  source_kinds?: SourceKind[],           // défaut : toutes
  include_sources?: boolean,             // défaut true (chunks)
  freshness_days?: number,               // surcharge globale des politiques
  max_classification?: 0|1|2|3,          // plafond supplémentaire
  min_relevance?: number,                // défaut settings.min_relevance
  session_id?: string,
  base_snapshot?: { name: string, version?: number },
  save_snapshot?: { name: string },
  explain?: boolean,                     // défaut true pour humains ; agents : false (compteurs uniquement)
  mode?: "full"|"progressive",           // progressive : résumé + index d'identifiants, détail via expand_source / get_decision…
  cache_hints?: boolean,                 // blocs de texte avec points d'arrêt cache_control (format Anthropic)
  as_of?: datetime                       // mémoire « telle que connue au » (§D2) : versions connues et valides à cette date
}

ContextPackage = {
  request_id, trace_id, task, intent, created_at,
  context: string,                       // Markdown assemblé avec citations [S1]…
  items: ContextItem[],                  // retenus, ordre de présentation
  excluded: ExcludedItem[],              // vide si explain=false
  exclusion_summary: Partial<Record<ReasonCode, number>>,
  tokens_used, token_budget,
  candidates_count,
  timings: { understand, retrieve, fuse, rerank, govern, select, compress, package, total },   // ms
  snapshot: { id, name, version } | null,
  config: { retrieval: "hybrid-bm25-knn-rrf-v1", reranker: string, embedding_model: string, llm: string | null },
  warnings: string[],                    // ex. "Le contexte contient des informations classifiées C2 (Confidentiel)."
  max_classification: 0|1|2|3,           // plus haut niveau du contenu livré dans items[] (0 s'il n'y en a pas)
  orion_project_id: uuid | null,         // id du projet commun aux services ORION (NOV-106, additif)
  schema_version: 2                      // version du contrat ; absent = 1 (cf. « Versions du contrat »)
}

ContextItem = { citation: "S1", candidate_type: CandidateType, id, document_id?, memory_item_id?, title, source_kind?,
                memory_kind?, memory_scope?, uri?, version?, excerpt /* texte compressé servi */, tokens,
                scores: Scores, classification, date /* source_updated_at ou valid_from */, pii_redacted: bool,
                access_scope: "public"|"project"|"restricted"|null,
                reason_code: "INCLUDED_RELEVANT"|"INCLUDED_PINNED", reason_detail }
ExcludedItem = { candidate_type, id?: uuid, title?: string, excerpt?: string, source_kind?, memory_kind?,
                 classification?, scores: Scores, reason_code: ReasonCode, reason_detail: string, redacted: bool,
                 related_citation?: string /* ex. doublon de S3 */ }
Scores = { bm25?: number, dense?: number, rrf?: number, rerank?: number, freshness?: number, final: number }
```

| Méthode | Chemin | Rôle | Corps / Query | Réponse |
|---|---|---|---|---|
| GET | `/projects/{slug}/context/requests` | viewer | `agent_id?, page` | `Page<ContextRequestSummary>` |
| GET | `/projects/{slug}/context/requests/{id}` | viewer | — | `ContextPackage` reconstitué (+ `feedback[]`) |
| POST | `/projects/{slug}/context/requests/{id}/complete` | viewer **(agent)** | `{missing: string[1..10], snapshot?: {name}, token_budget?}` | `ContextCompletion` : réassemble le contexte autour des manques signalés (boucle « contexte manquant ») ; le résultat est la version suivante du snapshot ; un agent ne complète que ce qu'il a reçu (sinon `404`) |
| POST | `/projects/{slug}/context/requests/{id}/feedback` | viewer **(agent)** | `{rating, comment?, item_flags?: {citation, flag}[]}` | `{id}` |

**Provenance d'accès et classification (v2).** `items[].access_scope` résume qui peut lire la source, **sans jamais exposer les
entrées d'ACL** : `restricted` dès qu'une ACL de la source (fragment ou document) est plus étroite que « tout le projet »
(rôle, utilisateur nommé), vide ou inconnue (fail-closed) ; sinon `public` (C0) ou `project` (C1 et plus). Il vaut `null` pour un
lecteur qui n'a pas le droit de lire l'item (restreint ou partiellement masqué dans une requête reconstituée, jamais pour
l'agent ou l'utilisateur qui a reçu le contexte). `max_classification` est le plus haut niveau du contenu **effectivement livré** au
lecteur : un item masqué pour lui n'y compte pas. Un artefact dérivé d'un contexte est au moins de ce niveau.

```ts
ContextCompletion = { request_id /* nouvelle requête */, completes /* requête d'origine */, snapshot: {id,name,version}|null,
                      added: { citation, id, title, source_kind?, memory_kind?, classification }[], still_missing: string[],
                      sufficiency: ContextSufficiency|null, tokens_used }
```

```ts
ContextRequestSummary = { id, trace_id, task, intent, agent: {id,name,kind}|null, user: {id, full_name}|null,
                          latency_ms, tokens_used, token_budget, included_count, excluded_count, candidates_count,
                          snapshot: {name, version}|null, rating: number|null, created_at }
```

## Snapshots

| Méthode | Chemin | Rôle | Réponse |
|---|---|---|---|
| GET | `/projects/{slug}/snapshots` | viewer | `{name, latest_version, versions: number, updated_at, last_task}[]` |
| GET | `/projects/{slug}/snapshots/{name}` | viewer | `SnapshotSummary[]` (versions, desc) |
| GET | `/projects/{slug}/snapshots/{name}/{version}` | viewer **(agent)** | `Snapshot` (`latest` accepté comme version) |
| GET | `/projects/{slug}/snapshots/{name}/diff?from=&to=` | viewer | `{from, to, added: SnapshotItem[], removed: SnapshotItem[], unchanged: SnapshotItem[]}` |

```ts
SnapshotSummary = { id, name, version, parent_version, task, intent, token_count, items_count, content_hash, created_by_label, created_at }
Snapshot = SnapshotSummary & { content: string, items: SnapshotItem[], request_id,
                               max_classification: 0|1|2|3, orion_project_id: uuid | null, schema_version: 2 }
SnapshotItem = { key /* "chunk:<id>" | "memory:<lineage_id>" */, citation, candidate_type, id, title, excerpt, source_kind?, memory_kind?, version?, forgotten: bool,
                 classification: 0|1|2|3|null /* null : item masqué, oublié ou niveau inconnu pour ce lecteur */ }
```

`SnapshotItem.classification` est enregistré avec le snapshot et n'est jamais inférieur au niveau actuel de l'item (relu à chaque
lecture ; pour les snapshots créés avant la v2, qui ne l'ont pas stocké, le niveau actuel est utilisé). `max_classification` ne compte
que les items dont le contenu est livré au lecteur (ni masqués, ni oubliés). Même règle pour l'outil MCP `get_snapshot`.

## Versions du contrat

`ContextPackage` et `Snapshot` portent `schema_version`. **v1** : implicite (champ absent). **v2** : ajoute `schema_version`,
`max_classification`, `ContextItem.access_scope` et `SnapshotItem.classification`, ainsi que `GET /agents/self`. Les évolutions sont
**additives** : aucun champ n'est renommé ni supprimé ; un consommateur v1 ignore les clés qu'il ne connaît pas, un consommateur v2
traite l'absence de `schema_version` comme la v1 et celle des nouveaux champs comme « inconnu » (donc restreint).

`orion_project_id` (NOV-106) est ajouté à `ContextPackage`, `Snapshot` et `Project` **sans changer `schema_version`** (2) : champ
optionnel et additif, le sens des champs existants ne change pas. Les payloads de webhook portent en plus `workspace_id` et
`orion_project_id` (clés de premier niveau, additives).

## Espaces et isolation (ADR 001, NOV-106)

Un **espace** (`workspaces`, `orion_workspace_id`) est la frontière d'isolation d'une entreprise. `workspace_id` figure sur les
utilisateurs, projets, clés d'agent et webhooks (obligatoire, immuable, défaut = espace par défaut `ORION_DEFAULT_WORKSPACE_ID`
créé par la migration `h009`). Documents, chunks, mémoires, snapshots, requêtes de contexte et index de recherche héritent de
l'espace **par leur projet** (aucune réindexation). L'espace d'une requête vient de l'identité validée (compte ou clé d'agent),
jamais d'un paramètre, d'un en-tête ou d'un corps. `ORBIT_WORKSPACE_ENFORCEMENT` :

| Valeur | Effet |
|---|---|
| `off` (défaut) | aucun filtre : comportement historique à l'identique |
| `shadow` | le filtre est évalué ; chaque accès inter-espaces incrémente `orbit_workspace_violations_total{mode,surface}` et est journalisé, la requête est servie |
| `enforce` | une ressource d'un autre espace répond `404`, identique à un identifiant inconnu (projets, documents, recherche, contexte, listes, membres, comptes) ; l'administrateur de plateforme ne traverse pas non plus |

En `enforce`, la mémoire d'organisation (`project_id NULL`) appartient à l'espace par défaut : elle n'est servie qu'aux projets de cet espace.

## OIDC relying party (NOV-109)

Désactivé par défaut (`ORBIT_OIDC_ENABLED=false` : aucune route d'authentification ne change, les routes `/auth/oidc/*` répondent 404).
Activé, il s'ajoute au mot de passe, à la session et aux clés `orb_…` (double pile, inchangés).

* **Jeton Bearer de l'IdP** (RS256, JWKS en cache rechargé à un `kid` inconnu) validé par le contrat de claims partagé
  (`backend/app/orion_claims.py`, copie vérifiée par hash de NOVA, `contracts/claims/`) : `iss`, `aud=orbit`, `exp`, `nbf`.
  Il désigne le compte **lié** (`external_identities`) ; l'espace est celui du jeton (`orion_workspace_id`, égal à celui du compte),
  un jeton sans espace ou de compte de service est refusé (403), `orion_project_id` restreint l'accès à ce projet,
  le rôle fonctionnel reste l'appartenance locale, `habilitation = min(User.clearance, orion_clearance)`, et `orbit-admin` ne
  donne l'administration qu'à un compte déjà administrateur local.
* **Navigateur** : `GET /auth/oidc/login` (Authorization Code + PKCE S256, state, nonce) puis `GET /auth/oidc/callback` :
  sujet lié → cookie de session ORBIT ; sujet inconnu avec e-mail **vérifié** correspondant à un compte du même espace →
  `202 {status: "link_required", link_token}` (rien n'est lié) ; sinon 403 (aucun compte n'est créé sauf `ORBIT_OIDC_AUTO_PROVISION=true`).
* **Liaison confirmée** : `POST /auth/oidc/link/confirm {link_token, password}` (mot de passe local du compte) crée la liaison
  et ouvre la session ; le jeton de liaison dure 10 min et se brûle après 5 mots de passe faux. `GET` / `DELETE /auth/oidc/identity` :
  voir / supprimer ses propres liaisons.
* Un utilisateur désactivé dans l'IdP perd l'accès à l'expiration du jeton ; les événements de révocation (NOV-80) sont inchangés.

## Observabilité & audit

| Méthode | Chemin | Rôle | Query | Réponse |
|---|---|---|---|---|
| GET | `/projects/{slug}/metrics` | viewer | `days=14` | `Metrics` |
| GET | `/projects/{slug}/audit` | viewer | `action?, page` | `Page<AuditEvent>` |
| GET | `/projects/{slug}/traces/export` | owner | `days=30` | NDJSON (une ligne par requête : requête, décisions, timings, feedback) |
| GET | `/projects/{slug}/compliance/report` | owner | `format=json\|html`, `request_id`, `memory_id`, `from`, `to` | Rapport de traçabilité IA (AI Act) : contexte, sources, décisions, modèle, garde-fous ; audité |
| GET | `/projects/{slug}/documents/quarantine` | owner | — | Fragments en quarantaine (score, signaux) |
| POST | `/projects/{slug}/documents/{id}/chunks/{chunk_id}/release` | owner | — | Libère un fragment de la quarantaine (audité, ré-extraction mémoire) |

```ts
Metrics = {
  totals: { requests, avg_latency_ms, p50_latency_ms, p95_latency_ms, tokens, cost_estimate, avg_rating, feedback_count },
  series: { date, requests, p50_latency_ms, p95_latency_ms, tokens, cost_estimate }[],   // un point par jour
  exclusions_by_reason: Partial<Record<ReasonCode, number>>,
  inclusions_by_type: Record<string, number>,              // chunk / memory:decision / ...
  top_sources: { document_id, title, source_kind, count }[],
  by_agent: { agent_id, name, kind, requests, avg_latency_ms, avg_tokens }[],
  stage_latency_avg: Record<string, number>,                // understand/retrieve/...
  ingestion: { documents_by_status: Record<DocumentStatus, number>, jobs_by_status: Record<JobStatus, number>, avg_ingest_ms }
}
```

## Système

`GET /health` → `{status:"ok"}` · `GET /ready` → état Postgres/OpenSearch/Valkey/modèle · `GET /metrics` (Prometheus) ·
`GET /api/v1/meta` → `{version, embedding_model, reranker, llm, reason_codes: {code: libellé}}`.

## MCP (`/mcp`, streamable HTTP, clé API d'agent obligatoire)

Outils :
- `get_context(task, intent?, token_budget?, scopes?, on_behalf_of?, session_id?, base_snapshot?, save_snapshot?, cache_hints?, mode?, as_of?)` → `{context, citations[], exclusion_summary, request_id, snapshot}` (`mode="progressive"` ajoute `index`, `as_of` sert la mémoire telle que connue à une date)
- `get_snapshot(name, version?)` → `Snapshot`
- `search_sources(query, limit?)` → `SearchHit[]`
- `propose_memory(kind, title, content, scope?, provenance_document_ids?)` → `MemoryItem` (statut `proposed`)
- `record_turn(session_id, role, content)` → `{turns, expires_at}`
- `send_feedback(request_id, rating, comment?)` → `{id}`
- `list_skills(task_type?)` → `{skills: Skill[]}` · `get_skill(name)` → `Skill & {skill_md}` (§D1 façons de faire)
- Contexte à la demande (mode `progressive`) : `expand_source(source_id)` (texte complet d'un extrait ou d'un document), `get_decision(decision_id)`, `get_memory_item(item_id)`, `search_more(query)` (recherche complémentaire ; chaque résultat indique l'outil de détail)

Au-delà des outils (§E4, SDK `mcp` 2.2) :
- *resources* : `orbit://about` (index statique) ; modèles `orbit://decisions{?limit}`, `orbit://decisions/{decision_id}`,
  `orbit://snapshots{?limit}`, `orbit://snapshots/{name}/{version}`, `orbit://skills{?task_type}`, `orbit://skills/{name}` (SKILL.md) —
  même authentification, visibilité et balisage « données non fiables » que les outils ;
- *prompts* : `rediger_spec(sujet)`, `preparer_revue(sujet?)`, `resumer_changements(jours?)` (contexte gouverné intégré) ;
- *elicitation* : `preparer_revue` sans sujet renvoie un `InputRequiredResult` (formulaire « sujet ») aux clients en protocole
  `2026-07-28` (aller-retour sans état) ; les clients plus anciens reçoivent un sujet par défaut.

## Évaluation & interopérabilité (§E)

Sous `/api/v1/projects/{slug}/evaluation` :
- `GET|POST /sets` · `GET|DELETE /sets/{id}` · `POST /sets/{id}/cases` `{question, expected:[{type:"memory"|"document", id, title?}]}` ·
  `DELETE /sets/{id}/cases/{case_id}` · `POST /sets/{id}/generate` `{limit?}` (génération assistée depuis les décisions validées) ;
- `POST /sets/{id}/runs` `{k?, min_recall?}` → 202 (tâche `evaluate`) · `GET /runs?set_id=` · `GET /runs/{id}` (métriques
  `recall`, `ndcg`, `sufficiency`, `citation_faithfulness`, détail par question) · `GET /compare?base=&target=` · `GET /settings` ;
- `GET /ranking-weights` (poids en vigueur, défauts, bornes, journal) · `POST /ranking-weights/learn` · `POST /ranking-weights/{change_id}/revert` ·
  `POST /ranking-weights/reset` (owner) ;
- `GET /judgements` (verdicts du LLM-juge, moyenne glissante, alertes) · `GET /judgements/export?days=` (NDJSON FORGE, owner, audité).

CLI (CI) : `python -m app.admin eval --project <slug> [--set <nom>] [--k 5] [--min-recall 0.6] [--as <email>] [--json]` → code 0 si tous
les jeux passent, 1 sous le seuil, 2 en cas d'erreur d'usage.

A2A (protocole **0.3.0**) : `GET /.well-known/agent-card.json` (alias `/.well-known/agent.json`) ·
`POST /api/v1/projects/{slug}/a2a/handoffs` `{snapshot:"nom@version", audience:"agent:<id>"|"user:<id>"|URL}` → `{handoff_id, token, expires_at}`
(JWS compact HS256, `typ` `orbit-context-handoff+jwt`) · `POST /api/v1/projects/{slug}/a2a/handoffs/receive` `{token}` → snapshot filtré selon
les droits du destinataire ; 401 signature invalide/expirée, 403 destinataire ou projet différent, 409 rejeu ou snapshot modifié.

OpenTelemetry GenAI (§E6) : spans `chat {model}` (`gen_ai.operation.name=chat`, `gen_ai.provider.name`, `gen_ai.request.*`, `gen_ai.usage.*`),
`context.retrieve` (`gen_ai.operation.name=retrieval`, `gen_ai.data_source.id`), spans MCP du SDK (`mcp.method.name`, `gen_ai.tool.name`) enrichis de
`gen_ai.agent.id|name` et `mcp.resource.uri`, juge (`gen_ai.evaluation.*`).
