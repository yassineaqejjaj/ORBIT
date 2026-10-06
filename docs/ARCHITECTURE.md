# ORBIT — Architecture de référence (contrat d'implémentation)

> Ce document est **la source de vérité** pour tous les contributeurs. Toute divergence
> entre le code et ce document est un bug, sauf si ce document est mis à jour dans le même changement.

ORBIT fournit à chaque agent IA les informations utiles à sa tâche, au bon moment, en tenant
compte de leur **pertinence**, **fraîcheur**, **provenance** et des **droits d'accès**.
Il doit toujours pouvoir expliquer **ce qui a été retenu, pourquoi, d'où cela provient et ce qui a été exclu**.

Flux : `Sources métier → ingestion & normalisation → indexation → gouvernance → assemblage du contexte → agents IA → observation & évaluation`.

---

## 1. Déploiement

`docker compose up` démarre une plateforme complète et opérationnelle :

| Service | Image | Rôle | Port hôte |
|---|---|---|---|
| `postgres` | `postgres:17-alpine` | Référentiel (source de vérité), file de jobs | 5433 |
| `opensearch` | `opensearchproject/opensearch:2.19.x` (security plugin désactivé en local) | BM25 (analyseur français) + k-NN + filtres | 9201 |
| `valkey` | `valkey/valkey:8-alpine` | Mémoire court terme (buffer de session), cache | 6380 |
| `api` | `backend/Dockerfile` | FastAPI : API REST `/api/v1`, serveur MCP `/mcp`, `/metrics` | 8000 |
| `worker` | `backend/Dockerfile` (commande `python -m app.worker`) | Pipeline d'ingestion, consolidation mémoire, oubli | — |
| `web` | `frontend/Dockerfile` | Next.js (UI), proxy `/api/*` → `api:8000` | 3000 |

- Le modèle d'embeddings est **téléchargé au build** de l'image backend (fonctionne ensuite hors-ligne).
- Stockage des fichiers bruts : volume `orbit_objects` monté sur `/data/objects` (abstraction `ObjectStore`, backend local ; S3 prévu).
- Migrations Alembic exécutées au démarrage de `api` (`alembic upgrade head`), puis création/validation des index OpenSearch.
- `make seed` (ou `docker compose exec api python -m app.seed`) charge le projet de démonstration **via le vrai pipeline**.

### Configuration (variables d'environnement, préfixe `ORBIT_`)

| Variable | Défaut | Description |
|---|---|---|
| `ORBIT_DATABASE_URL` | `postgresql+asyncpg://orbit:orbit@postgres:5432/orbit` | |
| `ORBIT_OPENSEARCH_URL` | `http://opensearch:9200` | |
| `ORBIT_VALKEY_URL` | `redis://valkey:6379/0` | |
| `ORBIT_JWT_SECRET` | (requis en prod, valeur dev dans `.env.example`) | HS256 |
| `ORBIT_JWT_TTL_MINUTES` | `720` | |
| `ORBIT_COOKIE_SECURE` | `false` | |
| `ORBIT_OBJECT_STORE_PATH` | `/data/objects` | |
| `ORBIT_EMBEDDING_PROVIDER` | `fastembed` | `fastembed` \| `openai` (TEI/vLLM/LiteLLM compatible OpenAI) \| `hash` (tests) |
| `ORBIT_EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | |
| `ORBIT_EMBEDDING_DIM` | `384` | doit correspondre au modèle |
| `ORBIT_EMBEDDING_BASE_URL` / `ORBIT_EMBEDDING_API_KEY` | vide | provider `openai` |
| `ORBIT_RERANKER` | `heuristic` | `heuristic` \| `fastembed` (cross-encoder) \| `none` |
| `ORBIT_RERANKER_MODEL` | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | Apache-2.0, multilingue (§B2) |
| `ORBIT_LLM_BASE_URL` / `ORBIT_LLM_MODEL` / `ORBIT_LLM_API_KEY` | vide | LLM **optionnel** compatible OpenAI (vLLM, Ollama, LiteLLM). Sans LLM, tout fonctionne en mode déterministe (règles + extraction). |
| `ORBIT_OTLP_ENDPOINT` | vide | Export OpenTelemetry (Langfuse, Jaeger, Tempo…) |
| `ORBIT_INDEX_PREFIX` | `orbit` | Index : `{prefix}-chunks-v1`, `{prefix}-memory-v1` |
| `ORBIT_COST_PER_1K_TOKENS` | `0.002` | Estimation de coût (EUR) des contextes servis |

---

## 2. Arborescence

```
orbit/
  docker-compose.yml  .env.example  Makefile  README.md
  docs/ARCHITECTURE.md  docs/API.md  docs/DEMO.md
  backend/
    pyproject.toml (uv, Python 3.12)  Dockerfile  alembic.ini  alembic/versions/
    app/
      main.py            # FastAPI app, montage routers, /mcp, /health, /ready, /metrics
      config.py          # Settings (pydantic-settings)
      db.py              # engine async, session, Base
      deps.py            # dépendances FastAPI : current_user, current_principal, project access
      security.py        # hash argon2, JWT, API keys agents
      enums.py           # TOUS les enums (cf. §4) — importés partout, jamais redéfinis
      models/            # SQLAlchemy 2.0 (un fichier par agrégat)
      schemas/           # Pydantic v2 (contrat API, cf. docs/API.md)
      api/               # routers FastAPI (auth, users, projects, members, agents, sources, documents,
                         #   jobs, memory, sessions, context, snapshots, metrics, audit, search)
      services/          # logique métier transverse (audit, projects, access)
      storage/           # ObjectStore
      ingestion/         # pipeline : extractors/, chunker, pii, classifier, metadata, pipeline, importers
      search/            # embeddings, opensearch (mappings, client), hybrid (BM25+kNN+RRF), rerank, tokens
      memory/            # extractor, lifecycle, consolidation, short_term (Valkey), conflicts
      governance/        # policy (codes de raison), acl, freshness
      context/           # assembler (orchestrateur), selection, compression, citations, snapshots
      llm/               # client optionnel OpenAI-compatible
      observability/     # tracing OTel, métriques Prometheus, enregistrement des requêtes
      mcp_server.py      # serveur MCP (FastMCP, streamable HTTP) monté sur /mcp
      worker.py          # boucle worker (file de jobs Postgres, SKIP LOCKED)
      seed/              # données de démonstration + seed.py
    tests/               # pytest (unit + intégration)
  frontend/
    Next.js 15 (App Router) + TypeScript strict + Tailwind CSS v4 + Radix UI + TanStack Query + Recharts + lucide-react
```

---

## 3. Sécurité & modèle d'accès

### Identités
- **Utilisateurs** : email + mot de passe (argon2). Session = JWT HS256 dans le cookie httpOnly `orbit_session`
  (SameSite=Lax). `Authorization: Bearer <jwt>` accepté aussi.
- **Agents** : clé API par agent, rattachée à un projet. Format `orb_<prefix8>_<secret32>` ; seul le hash (sha256) est stocké,
  la clé complète n'est montrée qu'une fois. Envoyée via `Authorization: Bearer orb_…` ou `X-Orbit-Key`.
  Un agent agit **pour le compte d'un utilisateur** (`on_behalf_of`, membre du projet) ; sans `on_behalf_of`, il n'a accès
  qu'aux contenus `project:*`.
- `is_admin` : super-utilisateur plateforme.

### Rôles projet
`owner` (gère membres, agents, paramètres, oubli) ⊃ `editor` (ingère, gère la mémoire, lance des contextes) ⊃ `viewer` (lecture, explorateur).

### Classification (alignée sur la politique de l'organisation)
| Niveau | Code | Libellé |
|---|---|---|
| 0 | `C0` | Public |
| 1 | `C1` | Interne |
| 2 | `C2` | Confidentiel |
| 3 | `C3` | Secret |

Chaque utilisateur et chaque agent a une **habilitation** (`clearance`, 0–3). Un contenu est servi seulement si
`classification ≤ min(clearance utilisateur, clearance agent, max_classification de la requête)`.
L'UI affiche un **bandeau d'avertissement** dès qu'un contenu C2/C3 est affiché, ingéré ou servi.

### ACL de contenu
`acl_principals: text[]` sur documents, chunks et items mémoire :
- `project:*` — tous les membres du projet (défaut)
- `role:owner`, `role:editor` — membres ayant au moins ce rôle
- `user:<uuid>` — utilisateur nommé

Un principal satisfait l'ACL s'il matche **au moins une** entrée. Items mémoire dérivés : ACL = **intersection la plus
restrictive** des sources (en pratique : si une source est restreinte, l'item hérite de ses principals ; classification = max des sources).
Mémoire `user` : visible uniquement de `subject_user_id` (et des agents agissant pour lui) — ACL `user:<subject>`.

### Principe de non-fuite
Les exclusions pour `EXCLUDED_ACL`/`EXCLUDED_CLASSIFICATION` sont journalisées **mais caviardées** (`redacted: true`,
ni titre, ni extrait, ni id) pour tout appelant qui n'aurait pas lui-même accès au contenu. Les agents ne reçoivent
que des **compteurs** d'exclusion. Les owners/admins voient le détail dans l'Explorateur (audit).

### Données personnelles
Détectées à l'ingestion (regex robustes : email, téléphone FR/international, IBAN, carte bancaire avec Luhn,
NIR, IPv4 ; + noms via motif de civilité ; adaptateur Presidio optionnel). Stockées sur le chunk (`pii` : liste
d'entités avec type/offsets) ; `text_redacted` = texte avec `[EMAIL]`, `[TÉLÉPHONE]`, … **Le contexte servi aux agents utilise
toujours `text_redacted`** et marque `pii_redacted: true`.

---

## 4. Enums (backend `app/enums.py`, frontend `src/lib/enums.ts` — valeurs identiques)

```
Role              = owner | editor | viewer
SourceKind        = document | note | ticket | crm | feedback | agent_trace | url
DocumentStatus    = pending | processing | indexed | failed | forgotten
ChunkStatus       = active | superseded | forgotten
JobKind           = ingest | reindex | forget | consolidate | extract_memory
JobStatus         = queued | running | succeeded | failed
MemoryScope       = short_term | project | user | long_term
MemoryKind        = decision | requirement | constraint | fact | preference | summary | risk
MemoryStatus      = proposed | validated | superseded | obsolete | forgotten
MemoryEventType   = created | edited | validated | superseded | obsoleted | forgotten | restored | conflict_detected
RelationType      = supersedes | contradicts | derived_from | mentions | constrains | relates_to
CandidateType     = chunk | memory | session
Intent            = general | specification | design | engineering | research | analysis | validation
ReasonCode        = INCLUDED_RELEVANT | INCLUDED_PINNED
                  | EXCLUDED_ACL | EXCLUDED_CLASSIFICATION | EXCLUDED_SCOPE | EXCLUDED_STALE | EXCLUDED_EXPIRED
                  | EXCLUDED_SUPERSEDED | EXCLUDED_CONFLICT | EXCLUDED_DUPLICATE | EXCLUDED_LOW_SCORE
                  | EXCLUDED_BUDGET | EXCLUDED_FORGOTTEN | EXCLUDED_QUARANTINE
AgentKind         = product | design | engineering | research | custom
```

Libellés FR des codes de raison (UI) :
| Code | Libellé | Détail attendu dans `reason_detail` |
|---|---|---|
| `INCLUDED_RELEVANT` | Retenu — pertinent | « score 0,82 · décision validée · 12 j » |
| `INCLUDED_PINNED` | Retenu — hérité du snapshot | « snapshot spec-atlas@v2 » |
| `EXCLUDED_ACL` | Exclu — accès non autorisé | (caviardé si l'appelant n'a pas accès) |
| `EXCLUDED_CLASSIFICATION` | Exclu — classification trop élevée | « C3 > habilitation C1 » |
| `EXCLUDED_SCOPE` | Exclu — hors périmètre demandé | « mémoire utilisateur d'un autre utilisateur » / « portée non demandée » |
| `EXCLUDED_STALE` | Exclu — information périmée | « 214 j > 180 j (tickets) » |
| `EXCLUDED_EXPIRED` | Exclu — mémoire court terme expirée | |
| `EXCLUDED_SUPERSEDED` | Exclu — remplacé | « remplacé par “Décision : PWA” (v2, 2026-09-02) » |
| `EXCLUDED_CONFLICT` | Exclu — contradiction résolue | « contredit par une source plus récente/validée : … » |
| `EXCLUDED_DUPLICATE` | Exclu — doublon | « quasi-identique à [S3] » |
| `EXCLUDED_LOW_SCORE` | Exclu — pertinence insuffisante | « score 0,21 < seuil 0,35 » |
| `EXCLUDED_BUDGET` | Exclu — budget de tokens atteint | « 380 tokens, budget restant 120 » |
| `EXCLUDED_FORGOTTEN` | Exclu — oubli sélectif | « oublié le … par … » |
| `EXCLUDED_QUARANTINE` | Exclu — quarantaine (injection suspectée) | « injection de prompt suspectée (score 0,88) » — évalué après ACL/classification (AI_CONTEXT_ENGINEERING.md §A1) |

---

## 5. Modèle de données (PostgreSQL)

Conventions : PK `id uuid` (uuid4 côté app), `created_at timestamptz default now()`, `updated_at` sur les tables mutables,
FK `ON DELETE CASCADE` vers `projects`. Enums stockés en `text` + `CHECK` (pas d'ENUM Postgres, migrations plus simples).

```
users(id, email UNIQUE, full_name, password_hash, is_admin bool, clearance smallint 0..3 default 1,
      avatar_color text, created_at, last_login_at)

projects(id, slug UNIQUE, name, description, settings jsonb, created_by → users, created_at, updated_at)
  settings = { "freshness_days": {"document":365,"note":120,"ticket":90,"crm":180,"feedback":180,"agent_trace":30,"url":180},
               "default_token_budget": 4000, "min_relevance": 0.35, "short_term_ttl_hours": 72 }

project_members(project_id, user_id, role, created_at)  PK(project_id,user_id)

agents(id, project_id, name, kind, description, clearance smallint, api_key_prefix UNIQUE, api_key_hash,
       active bool, created_by, created_at, last_used_at)

sources(id, project_id, name, kind, description, default_classification smallint, default_acl text[],
        config jsonb, created_at, updated_at, last_ingested_at)

documents(id, project_id, source_id, external_id NULL, title, uri NULL, mime_type, author NULL,
          classification smallint, acl_principals text[], tags text[], metadata jsonb,
          status, status_reason NULL, current_version int, pii_count int default 0,
          source_updated_at timestamptz,   -- date métier (fraîcheur)
          forgotten_at NULL, forgotten_by NULL, created_at, updated_at)
  UNIQUE(project_id, source_id, external_id) WHERE external_id IS NOT NULL

document_versions(id, document_id, version int, content_hash, object_key NULL, size_bytes,
                  extracted_text, metadata jsonb, created_at)   UNIQUE(document_id, version)

chunks(id, project_id, document_id, version int, ordinal int, text, text_redacted, token_count int,
       section text NULL, char_start int, char_end int, pii jsonb default '[]', classification smallint,
       acl_principals text[], status, created_at)
  INDEX(document_id, version)

ingestion_jobs(id, project_id, document_id NULL, kind, status, attempts int, max_attempts int default 3,
               payload jsonb, error NULL, steps jsonb default '[]',   -- [{name, status, started_at, duration_ms, detail}]
               locked_by NULL, locked_at NULL, run_after timestamptz default now(),
               created_at, started_at NULL, finished_at NULL)
  INDEX(status, run_after)

memory_items(id, project_id NULL,  -- NULL = long_term organisationnel
             lineage_id uuid,      -- identique pour toutes les versions d'un même item
             version int default 1, is_current bool default true,
             scope, kind, status, title, content, confidence real (0..1),
             classification smallint, acl_principals text[], tags text[],
             subject_user_id NULL (scope=user), session_id NULL (scope=short_term), expires_at NULL,
             valid_from timestamptz, valid_to NULL,
             supersedes_id NULL, superseded_by_id NULL,
             created_by_type text (user|agent|system), created_by_id NULL,
             created_at, updated_at)
  INDEX(project_id, scope, status) ; INDEX(lineage_id)

memory_provenance(id, memory_item_id, document_id NULL, chunk_id NULL, context_request_id NULL,
                  source_label text, excerpt text, created_at)

memory_events(id, memory_item_id, lineage_id, event, actor_type, actor_id NULL, reason NULL, data jsonb, created_at)

relations(id, project_id, src_type (chunk|memory|document), src_id, rel_type, dst_type, dst_id,
          confidence real, detail NULL, created_at)   UNIQUE(src_id, rel_type, dst_id)

context_requests(id, project_id, trace_id text, agent_id NULL, user_id NULL (on_behalf_of), requested_by_type, requested_by_id,
                 task, intent, params jsonb, status (succeeded|failed), error NULL,
                 latency_ms int, timings jsonb, candidates_count int, included_count int, excluded_count int,
                 tokens_used int, token_budget int, cost_estimate numeric, snapshot_id NULL,
                 context_text text, created_at)

context_decisions(id, request_id, candidate_type, candidate_id, document_id NULL, memory_item_id NULL,
                  title, excerpt, source_kind NULL, classification smallint, scores jsonb,
                  included bool, reason_code, reason_detail, tokens int, rank int NULL, citation text NULL)

context_feedback(id, request_id, actor_type, actor_id, rating smallint 1..5, comment NULL, item_flags jsonb, created_at)

context_snapshots(id, project_id, name, version int, parent_id NULL, request_id NULL, task, intent,
                  content text, items jsonb, content_hash, token_count int,
                  created_by_type, created_by_id, created_at)   UNIQUE(project_id, name, version)

tombstones(id, project_id, target_type (document|memory|chunk), target_id, reason, requested_by, created_at, propagated_at NULL)

audit_log(id, project_id NULL, actor_type (user|agent|system), actor_id NULL, actor_label, action, target_type, target_id NULL,
          summary text, details jsonb, created_at)  INDEX(project_id, created_at DESC)
```

---

## 6. Index OpenSearch

`{prefix}-chunks-v1` et `{prefix}-memory-v1`, settings : `index.knn: true`, analyseur `french` personnalisé
(`elision` + `lowercase` + `asciifolding` + `french_stop` + `french_stemmer`).

Champs communs : `id` (keyword), `project_id` (keyword), `text` (text, analyzer french), `title` (text french, boost 2),
`embedding` (knn_vector, dim `ORBIT_EMBEDDING_DIM`, `hnsw`, `cosinesimil`, engine `lucene`), `classification` (integer),
`acl_principals` (keyword), `status` (keyword), `tags` (keyword), `created_at`, `source_updated_at` (date).
Chunks : `document_id`, `version`, `source_kind`, `section`. Mémoire : `lineage_id`, `scope`, `kind`, `subject_user_id`, `session_id`, `valid_to`, `expires_at`.

Les chunks `superseded` **restent indexés** (statut mis à jour) pour que la gouvernance puisse expliquer leur exclusion ;
les contenus **oubliés sont supprimés** de l'index (tombstone propagé) et n'apparaissent plus que dans l'audit.

---

## 7. Pipeline d'ingestion (worker)

File de jobs dans `ingestion_jobs` (`SELECT … FOR UPDATE SKIP LOCKED`, retries exponentiels, `steps` renseignés à chaque étape
pour l'écran Sources). Étapes d'un job `ingest` :

1. `extract` — extracteur selon MIME : PDF (pypdf), DOCX (python-docx), Markdown/texte, HTML (BeautifulSoup), JSON/CSV
   (tickets, CRM, feedback, traces via `importers`). Normalisation (espaces, césure, NFC).
2. `pii` — détection + `text_redacted`.
3. `classify` — classification C0–C3 : max(défaut de la source, niveau déclaré, règles mots-clés
   [« secret », « confidentiel », « salaire », « budget », « contrat », …], PII sensibles ⇒ ≥ C2) ; LLM si configuré.
4. `chunk` — découpage par structure (titres Markdown/HTML, paragraphes) puis fenêtre ~350 tokens, chevauchement 50.
5. `embed` — embeddings par lot.
6. `index` — upsert OpenSearch, anciennes versions → `superseded`.
7. `extract_memory` — enchaîne un job `extract_memory` : extraction des décisions, besoins, contraintes, risques, faits
   (règles FR : « Décision : », « Nous avons décidé », « il est décidé », « Besoin : », « En tant que … je veux »,
   « Contrainte : », « doit », « ne doit pas », « Risque : » ; LLM si configuré), création d'items `proposed`
   (ou `validated` si la source est un compte rendu de décision explicite), provenance → chunk, détection
   de remplacement/contradiction (cf. §8).

Nouvelle version d'un document (même `external_id` ou ré-upload du même titre dans la même source) ⇒ version+1,
chunks précédents `superseded`, relation `supersedes` document→document.

---

## 8. Mémoire

| Portée | Contenu | Stockage | Cycle de vie |
|---|---|---|---|
| `short_term` | Tours de session/tâche d'un agent | Valkey (buffer `orbit:session:{project}:{session}`, TTL) + items `short_term` avec `expires_at` | Expire (TTL projet), consolidé en `summary` projet à la clôture de session |
| `project` | Décisions, besoins, contraintes, risques, faits du projet | Postgres + index mémoire | proposé → validé → remplacé/obsolète/oublié |
| `user` | Préférences de l'utilisateur (style, format, rôle) | idem, `subject_user_id` | visible du seul sujet ; oubli à la demande (RGPD) |
| `long_term` | Faits consolidés, durables (niveau organisation, `project_id NULL`) ou projet | idem | consolidation périodique, décroissance de confiance |

- **Versionnement append-only** : toute modification crée une nouvelle ligne (même `lineage_id`, `version+1`),
  l'ancienne passe `is_current=false`. Événements dans `memory_events` (historique complet affiché dans l'UI).
- **Remplacement** : une nouvelle décision dont la similarité cosinus avec une décision `validated` du même projet > 0,80
  et provenant d'une source plus récente ⇒ la nouvelle `supersedes_id` l'ancienne, l'ancienne passe `superseded`
  (`superseded_by_id`), relation `supersedes`, événement ; réversible (`restore`).
- **Contradiction** : similarité > 0,70 et marqueurs divergents (négation, valeurs numériques différentes, antonymes) sans
  relation temporelle nette ⇒ relation `contradicts` + événement `conflict_detected`. À l'assemblage, la source la plus
  fiable gagne (validé > proposé, puis plus récent, puis confiance) ; l'autre ⇒ `EXCLUDED_CONFLICT`.
- **Oubli sélectif** : tombstone → suppression de l'index, statut `forgotten`, contenu remplacé par `[oublié]` en base
  (on garde titre/métadonnées pour l'audit), propagation aux items dérivés (items dont toutes les provenances sont
  oubliées ⇒ oubliés ; sinon confiance réduite), purge Valkey, snapshots marqués (items caviardés à l'affichage).

---

## 9. Assemblage du contexte (`POST /projects/{slug}/context`)

Étapes chronométrées (`timings` en ms, affichées en cascade dans l'Explorateur) :

1. `understand` — normalisation de la tâche, intention (fournie ou déduite par mots-clés), extraction de termes clés,
   embedding de la requête.
2. `retrieve` — en parallèle : BM25 chunks (top 40), kNN chunks (top 40), BM25+kNN mémoire (top 30),
   tours de session (Valkey) si `session_id`, items épinglés du snapshot de base. **Filtre de pré-sélection = projet uniquement**
   (+ long_term org) ; les règles de gouvernance sont appliquées ensuite pour pouvoir **expliquer** chaque exclusion.
3. `fuse` — Reciprocal Rank Fusion (k=60) BM25/kNN, normalisation 0..1.
4. `rerank` — `heuristic` : score = 0,55·rrf_norm + 0,20·dense + 0,10·fraîcheur (décroissance exp., demi-vie 90 j)
   + 0,10·boost type (décision validée 1,0 ; besoin/contrainte 0,8 ; chunk 0,5) + 0,05·recouvrement de termes ;
   `fastembed` : cross-encoder puis même combinaison.
5. `govern` — pour chaque candidat, dans cet ordre (premier motif bloquant retenu) :
   FORGOTTEN → ACL → CLASSIFICATION → SCOPE → EXPIRED → STALE → SUPERSEDED → LOW_SCORE.
6. `select` — tri par score ; résolution des conflits (CONFLICT) ; dédoublonnage (cosinus > 0,92 ou Jaccard de
   shingles > 0,8 ⇒ DUPLICATE) ; MMR (λ=0,7) ; remplissage glouton sous budget (BUDGET).
7. `compress` — extraction des phrases les plus pertinentes de chaque item pour tenir le budget (LLM de synthèse si configuré),
   citations `[S1]…[Sn]` stables dans l'ordre de présentation.
8. `package` — Markdown structuré :
   `## Décisions en vigueur`, `## Besoins utilisateurs`, `## Contraintes & risques`, `## Faits & connaissances`,
   `## Préférences utilisateur`, `## Extraits de sources`, `## Session en cours`, puis `## Sources` (liste des citations :
   titre, type, version, date, uri).
9. `persist` — `context_requests` + `context_decisions` (+ snapshot si `save_snapshot`), trace OTel, métriques.

Objectif de performance : p95 < 1 500 ms sur le jeu de démonstration (CPU).

## 10. Snapshots de contexte

Contexte commun **versionné et immuable** : `name` (ex. `spec-atlas`) + `version` auto-incrémentée. Une requête avec
`base_snapshot` réinjecte les items du snapshot (`INCLUDED_PINNED`, sauf s'ils sont depuis oubliés/remplacés ⇒ exclus
avec le motif) puis complète par une nouvelle recherche. Diff entre versions (ajouts / retraits / inchangés).
Un agent design/engineering peut ainsi partir du contexte de l'agent produit.

## 11. Observabilité

- Chaque requête de contexte a un `trace_id` (OTel) ; spans par étape ; export OTLP si `ORBIT_OTLP_ENDPOINT`.
- Prometheus `/metrics` : `orbit_context_requests_total`, `orbit_context_latency_seconds` (histogramme),
  `orbit_context_tokens`, `orbit_ingestion_jobs_total{status}`, `orbit_exclusions_total{reason}`.
- API `metrics` agrège depuis Postgres pour l'UI ; export NDJSON des traces pour l'évaluation (FORGE).
- `context_feedback` : note 1–5 + drapeaux par citation (`irrelevant|outdated|wrong`) ⇒ `outdated` crée une
  proposition d'obsolescence sur l'item mémoire concerné.

## 12. Audit

Toute action significative écrit dans `audit_log` (connexion, création projet, ingestion, changement de statut mémoire,
oubli, création/révocation d'agent, requête de contexte, changement d'ACL/classification). Affiché dans la Vue projet.
