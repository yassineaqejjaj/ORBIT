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
User        = { id, email, full_name, is_admin: bool, clearance: 0|1|2|3, avatar_color: string, created_at }
Member      = { user: User, role: Role, created_at }
Project     = { id, slug, name, description, settings: ProjectSettings, role: Role /* rôle de l'appelant */, created_at, updated_at }
ProjectSettings = { freshness_days: Record<SourceKind, number>, default_token_budget: number, min_relevance: number, short_term_ttl_hours: number }
ProjectSummary = Project & { stats: { sources: number, documents: number, memory_items: number, context_requests_7d: number } }

Agent       = { id, name, kind: AgentKind, description, clearance, api_key_prefix, active, created_at, last_used_at }
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
| POST | `/projects/{slug}/agents` | owner | `{name, kind, description?, clearance}` | `AgentCreated` |
| POST | `/projects/{slug}/agents/{id}/rotate` | owner | — | `AgentCreated` |
| DELETE | `/projects/{slug}/agents/{id}` | owner | — | `204` (révocation : `active=false`) |

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
  explain?: boolean                      // défaut true pour humains ; agents : false (compteurs uniquement)
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
  warnings: string[]                     // ex. "Le contexte contient des informations classifiées C2 (Confidentiel)."
}

ContextItem = { citation: "S1", candidate_type: CandidateType, id, document_id?, memory_item_id?, title, source_kind?,
                memory_kind?, memory_scope?, uri?, version?, excerpt /* texte compressé servi */, tokens,
                scores: Scores, classification, date /* source_updated_at ou valid_from */, pii_redacted: bool,
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
| POST | `/projects/{slug}/context/requests/{id}/feedback` | viewer **(agent)** | `{rating, comment?, item_flags?: {citation, flag}[]}` | `{id}` |

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
Snapshot = SnapshotSummary & { content: string, items: SnapshotItem[], request_id }
SnapshotItem = { key /* "chunk:<id>" | "memory:<lineage_id>" */, citation, candidate_type, id, title, excerpt, source_kind?, memory_kind?, version?, forgotten: bool }
```

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
- `get_context(task, intent?, token_budget?, scopes?, on_behalf_of?, session_id?, base_snapshot?, save_snapshot?, as_of?)` → `{context, citations[], exclusion_summary, request_id, snapshot}`
- `get_snapshot(name, version?)` → `Snapshot`
- `search_sources(query, limit?)` → `SearchHit[]`
- `propose_memory(kind, title, content, scope?, provenance_document_ids?)` → `MemoryItem` (statut `proposed`)
- `record_turn(session_id, role, content)` → `{turns, expires_at}`
- `send_feedback(request_id, rating, comment?)` → `{id}`
- `list_skills(task_type?)` → `{skills: Skill[]}` · `get_skill(name)` → `Skill & {skill_md}` (§D1 façons de faire)
