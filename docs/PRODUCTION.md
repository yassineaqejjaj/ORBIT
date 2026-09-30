# ORBIT — Contrat « production readiness » (branche `production-readiness`)

> Source de vérité pour le durcissement production. Complète `ARCHITECTURE.md` et `API.md` (qui restent valables).
> Toute divergence code ↔ ce document est un bug, sauf mise à jour du document dans le même changement.
> Origine : audit de préparation production (6 dimensions, constats vérifiés). Chaque constat est rattaché à un chantier ci-dessous.

## 0. Décisions

| Sujet | Décision |
|---|---|
| Cible de déploiement | **Kubernetes** via chart Helm générique (`deploy/helm/orbit`) + **compose production mono-serveur** (`deploy/compose/`) avec reverse proxy **Caddy** (HTTPS automatique). Datastores : managés recommandés (Postgres managé ou CloudNativePG, OpenSearch managé ou opérateur, Valkey/Redis managé, S3). |
| Identité | **OIDC générique** (code + PKCE ; testé avec Keycloak, compatible Entra ID / Okta / Google). Comptes locaux conservés (désactivables), **MFA TOTP** pour comptes locaux. |
| Sessions | Sessions **côté serveur** (table `user_sessions`, id dans le JWT `sid`) : révocation, expiration d'inactivité (30 min) et absolue (12 h). |
| CSRF | Double-submit : cookie `orbit_csrf` (non httpOnly) + en-tête `X-CSRF-Token` obligatoire sur toute méthode non sûre authentifiée par cookie, + contrôle `Origin`/`Referer` ∈ `ORBIT_PUBLIC_URL`. Les appels par clé d'agent / Bearer en sont exemptés. |
| Chiffrement | TLS externe (Caddy/Ingress). TLS interne supporté par configuration (Postgres `sslmode`, OpenSearch https+CA, Valkey `rediss://`). Au repos : chiffrement disque/plateforme **plus** chiffrement applicatif enveloppe (AES-256-GCM, `cryptography`) des objets bruts et des secrets de connecteurs, clé maître `ORBIT_ENCRYPTION_KEY`. |
| Stockage objet | `ORBIT_OBJECT_STORE_BACKEND=local|s3` (S3 compatible via boto3). |
| Délégation agents | Un agent n'agit **pour le compte** d'un utilisateur que si celui-ci lui a accordé une **délégation** active (table `agent_delegations`). Un admin non membre n'est jamais promu owner via `on_behalf_of`. |
| Audit | Journal **append-only chaîné** (hash SHA-256 `prev_hash`/`hash`), trigger Postgres interdisant UPDATE/DELETE, plus de cascade (`project_id` → SET NULL). Lectures de contenus ≥ C2 journalisées (`data.read_restricted`). |
| Démo | La démo reste fonctionnelle : `make demo` = `make init` (génère `.env` avec secrets aléatoires, `ORBIT_DEMO_MODE=true`) + `up` + `seed`. Mot de passe démo **`orbit-demo-2026`** (politique ≥ 12 caractères). Le seed refuse de s'exécuter si `ORBIT_DEMO_MODE` n'est pas `true`. |

## 1. Nouvelles variables d'environnement (préfixe `ORBIT_`)

| Variable | Défaut | Rôle |
|---|---|---|
| `ENV` | `production` | `production` \| `development` \| `test`. En `production`, **fail-closed** (voir §2). |
| `DEMO_MODE` | `false` | Autorise le seed de démo et les comptes démo. |
| `PUBLIC_URL` | `http://localhost:3000` | URL publique (redirections OIDC, contrôle Origin CSRF, liens d'invitation). |
| `JWT_SECRET` | *aucun* (requis hors test/dev) | ≥ 32 octets aléatoires. `JWT_PREVIOUS_SECRETS` (liste CSV) pour rotation. |
| `SESSION_IDLE_MINUTES` / `SESSION_ABSOLUTE_HOURS` | `30` / `12` | |
| `COOKIE_SECURE` | `true` (forcé en production) | |
| `TRUSTED_PROXIES` | `127.0.0.1` | CIDR CSV des proxies dont on accepte `X-Forwarded-*` (remplace `--forwarded-allow-ips *`). |
| `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` | `admin@orbit.local` / *vide* | Vide ⇒ mot de passe aléatoire affiché **une fois** dans les logs, `must_change_password=true`. Le défaut historique `orbit-admin` est **refusé**. |
| `PASSWORD_MIN_LENGTH` | `12` | + refus des mots de passe triviaux (liste courte embarquée, égal à l'email, etc.). |
| `MFA_REQUIRED` | `privileged` | `none` \| `privileged` (admins + habilitation ≥ C2) \| `all` — comptes locaux uniquement (OIDC : MFA déléguée à l'IdP). |
| `OIDC_ENABLED`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_SCOPES` (`openid email profile`), `OIDC_LABEL` (`SSO entreprise`), `OIDC_GROUPS_CLAIM` (`groups`), `OIDC_ADMIN_GROUPS` (CSV), `OIDC_CLEARANCE_MAP` (JSON `{"groupe": niveau}`), `OIDC_DEFAULT_CLEARANCE` (`1`), `OIDC_ALLOW_LOCAL_LOGIN` (`true`), `OIDC_AUTO_PROVISION` (`true`) | | SSO |
| `RATE_LIMIT_LOGIN` / `RATE_LIMIT_API` / `RATE_LIMIT_AGENT` | `5/minute,20/hour` / `600/minute` / `300/minute` | Fenêtres glissantes Valkey ; verrouillage progressif du compte après échecs. |
| `DOCS_ENABLED` | `false` (production) | Swagger/OpenAPI. |
| `METRICS_TOKEN` | *vide* | Si défini, `/metrics` exige `Authorization: Bearer <token>` ; sinon `/metrics` n'est servi que sur le port interne `METRICS_PORT` (`9464`). |
| `OPENSEARCH_USER`, `OPENSEARCH_PASSWORD`, `OPENSEARCH_CA_CERTS`, `OPENSEARCH_VERIFY_CERTS` (`true`), `OPENSEARCH_SHARDS` (`1`), `OPENSEARCH_REPLICAS` (`1` prod / `0` dev) | | Index derrière des **alias** `{prefix}-chunks` / `{prefix}-memory` (index physiques versionnés). |
| `VALKEY_URL` | | `rediss://:password@host:6379/0` supporté. |
| `DATABASE_SSLMODE` (`prefer`), `DATABASE_CA_CERTS`, `DB_POOL_SIZE` (`10`), `DB_MAX_OVERFLOW` (`10`), `DB_STATEMENT_TIMEOUT_MS` (`30000`) | | |
| `OBJECT_STORE_BACKEND` (`local`), `S3_ENDPOINT`, `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_PREFIX` | | |
| `ENCRYPTION_KEY` / `ENCRYPTION_KEY_FILE` | *requis en production* | Clé maître base64 32 octets ; `ENCRYPTION_PREVIOUS_KEYS` pour rotation. |
| `RETENTION_CONTEXT_DAYS` (`180`), `RETENTION_FEEDBACK_DAYS` (`365`), `RETENTION_JOBS_DAYS` (`30`), `RETENTION_AUDIT_DAYS` (`1095`), `RETENTION_SESSIONS_DAYS` (`30`), `RETENTION_TOMBSTONE_DAYS` (`3650`) | | Purge quotidienne (worker, singleton). |
| `LLM_MAX_CLASSIFICATION` (`1`), `LLM_REDACT_PII` (`true`), `EXTERNAL_EMBEDDING_MAX_CLASSIFICATION` (`1`) | | Garde-fous des flux vers LLM/embeddings externes. |
| `API_WORKERS` | `2` | Processus uvicorn. |
| `MAX_UPLOAD_MB` / `MAX_UPLOAD_TOTAL_MB` | `50` / `200` | Upload streamé sur disque. |
| `SEMANTIC_CACHE_TTL_SECONDS` | `300` | Cache des contextes identiques (clé = tâche + paramètres + principal + version des données). |

## 2. Validation « fail-closed » au démarrage (`ENV=production`)

Refus de démarrer (message clair) si : `JWT_SECRET` absent/court/égal au défaut dev ; `COOKIE_SECURE=false` ;
`BOOTSTRAP_ADMIN_PASSWORD == "orbit-admin"` ou < 16 caractères (s'il est fourni) ; `ENCRYPTION_KEY` absente ;
`PUBLIC_URL` non https ; `DEMO_MODE=true` **sans** `ENV=development`… sauf si `ORBIT_ALLOW_INSECURE_DEMO=true`
(utilisé uniquement par `make demo` en local, avec avertissement bruyant) ; mot de passe Postgres/OpenSearch/Valkey par défaut.

## 3. Nouveaux endpoints (tous sous `/api/v1`, erreurs `{detail, code}` en français)

### Identité & compte (chantier SEC)
| Méthode | Chemin | Accès | Corps → Réponse |
|---|---|---|---|
| GET | `/auth/config` | public | `{local_login, oidc: {enabled, label}, mfa_policy, password_min_length}` |
| POST | `/auth/login` | public | `{email, password}` → `User` \| `{mfa_required: true, mfa_token}` \| `{password_change_required: true, change_token}` |
| POST | `/auth/mfa` | public | `{mfa_token, code}` (TOTP ou code de secours) → `User` |
| POST | `/auth/password/change-required` | public | `{change_token, new_password}` → `User` |
| GET | `/auth/oidc/login?next=` | public | 302 vers l'IdP (state + nonce + PKCE en cookie signé) |
| GET | `/auth/oidc/callback` | public | 302 vers `next` (session créée ; provisioning JIT, mapping groupes→admin/habilitation) |
| GET | `/auth/csrf` | public | `{csrf_token}` + cookie `orbit_csrf` |
| POST | `/auth/logout` | user | révoque la session serveur |
| GET | `/account/sessions` | user | `{id, created_at, last_seen_at, ip, user_agent, current}[]` |
| DELETE | `/account/sessions/{id}` | user | 204 |
| POST | `/account/password` | user | `{current_password, new_password}` → 204 (révoque les autres sessions) |
| POST | `/account/mfa/setup` | user | → `{secret, otpauth_uri, qr_svg}` |
| POST | `/account/mfa/enable` | user | `{code}` → `{recovery_codes: string[]}` |
| POST | `/account/mfa/disable` | user | `{password, code}` → 204 (interdit si politique l'exige) |
| GET | `/account/export` | user | export JSON de ses données personnelles (art. 15/20) — implémenté par COMPLIANCE |
| GET | `/account/delegations` | user | `AgentDelegation[]` |
| POST | `/projects/{slug}/delegations` | membre | `{agent_id, expires_at?, max_classification?}` → `AgentDelegation` |
| DELETE | `/projects/{slug}/delegations/{id}` | délégant ou owner | 204 |
| GET/POST/PATCH | `/users` (admin) | admin | + champs `is_active, must_change_password, mfa_enabled, auth_provider ("local"\|"oidc"), last_login_at` |
| POST | `/users/{id}/deactivate` · `/reactivate` · `/reset-password` (→ `{temporary_password}`) · `/mfa/reset` | admin | désactivation ⇒ sessions + délégations révoquées |
| POST | `/users/invitations` | admin | `{email, full_name, clearance, is_admin?}` → `{invite_url, expires_at}` |
| POST | `/auth/invitations/{token}/accept` | public | `{password}` → `User` |

Agents : nouveaux champs `expires_at` (défaut +180 j), `scopes: AgentScope[]`
(`context:read, search:read, snapshots:read, memory:propose, sessions:write, documents:write, feedback:write` ; défaut : tous sauf `documents:write`),
`previous_key_expires_at` (rotation : l'ancienne clé reste valide 24 h). `POST /projects/{slug}/agents` accepte `expires_at`, `scopes`.

`AgentDelegation = {id, project_id, agent: {id,name,kind}, user: {id, full_name}, max_classification, expires_at, created_at, revoked_at}`.

### Conformité (chantier COMPLIANCE)
| Méthode | Chemin | Accès | Détail |
|---|---|---|---|
| GET | `/compliance/users/{id}/export` | admin | même format que `/account/export` |
| POST | `/compliance/users/{id}/erase` | admin | `{reason}` → effacement art. 17 : pseudonymisation (`Utilisateur supprimé #xxxx`), mémoire `user` oubliée, sessions/délégations supprimées, turns Valkey purgés, contenu des contextes le concernant purgé ; audit conservé (pseudonymisé) |
| POST | `/projects/{slug}/archive` · DELETE `/projects/{slug}` | owner (+ confirmation `{confirm_slug}`) | archivage (lecture seule) puis purge complète (job) : index, objets, Valkey, lignes ; audit conservé |
| GET/PATCH | `/compliance/retention` | admin | politiques effectives + dernière exécution |
| GET | `/compliance/audit/verify` | admin | `{valid, checked, first_invalid_id, verified_at}` |
| GET | `/compliance/processing-register` | admin | registre des traitements (JSON généré depuis la config) |
| PATCH | `/projects/{slug}/documents/{id}` | **abaisser** la classification exige rôle owner + `justification` (≥ 10 car.) ; élargir l'ACL d'un document ≥ C2 idem ; événement `governance.classification_downgrade` |

### Exploitation (chantier OPS)
| Méthode | Chemin | Accès | Détail |
|---|---|---|---|
| GET | `/ops/status` | admin | files (backlog par statut/kind), workers (heartbeat), dépendances, versions d'index/alias, dernière maintenance |
| GET | `/ops/jobs/dead-letter` | admin | jobs `dead` (après `max_attempts` ou poison-pill) |
| POST | `/projects/{slug}/jobs/{id}/retry` · `/cancel` | editor | |
| GET | `/ops/index/drift?project=` | admin | écarts Postgres ↔ OpenSearch (manquants, orphelins, statuts) |
| POST | `/ops/index/reindex` | admin | `{project_slug?, target: "chunks"\|"memory"\|"all"}` → job ; réindexation **à chaud** vers un nouvel index physique puis bascule d'alias |
CLI équivalente : `python -m app.admin {status,drift,reindex,verify-audit,retention,backup-check}`.

### Connecteurs (chantier CONNECTORS, vague 2) et évaluation (vague 2)
Définis dans `docs/PRODUCTION.md §6` lors de la vague 2.

## 4. Migrations (chaîne linéaire pré-créée — chaque propriétaire remplit la sienne)

`0002_identity` (SEC) → `0003_compliance` (COMPLIANCE) → `0004_ops` (OPS) → `0005_connectors` (vague 2) → `0006_quality` (vague 2).
Ne jamais créer d'autre fichier de migration ; toujours rendre `downgrade()` exact. Tables nouvelles dans `app/models/{identity,compliance,connector}.py`.

## 5. Répartition des fichiers — vague 1

| Chantier | Propriétaire exclusif |
|---|---|
| **SEC** (identité, sessions, CSRF, rate limiting, délégations, clés d'agents, config fail-closed) | `app/config.py`, `app/security.py`, `app/deps.py`, `app/db.py`, `app/main.py`, `app/errors.py`, `app/identity/**` (nouveau), `app/api/{auth,users,agents,account,members,projects}.py` (sauf archive/delete projet → COMPLIANCE via `app/compliance/projects.py` + routes dans `api/compliance.py`), `app/services/users.py`, `app/governance/acl.py`, `app/context/assembler.py` (bloc `on_behalf_of` uniquement), `app/api/sessions.py` (restriction des transcripts), `app/mcp_server.py` (auth/délégation), `app/models/{user,agent,identity}.py`, migration `0002`, `app/seed/**` (adaptation démo : mot de passe, délégations, DEMO_MODE), tests associés |
| **COMPLIANCE** (effacement, DSAR, rétention, audit chaîné, lectures restreintes, déclassification, PII, garde-fous LLM, docs RGPD) | `app/compliance/**` (nouveau), `app/api/compliance.py`, `app/api/documents.py`, `app/api/metrics.py` (export NDJSON), `app/api/audit.py`, `app/services/audit.py`, `app/services/metrics.py`, `app/models/{audit,compliance}.py`, migration `0003`, `app/memory/lifecycle.py` (chemins d'oubli), `app/context/persistence.py`, `app/context/snapshots.py`, `app/ingestion/pii.py`, `app/llm/client.py`, `app/search/embeddings.py` (garde-fou provider externe), `docs/compliance/**`, tests associés |
| **OPS-RUNTIME** (files, DLQ, workers, observabilité, index/alias, drift, reindex, stockage S3 + chiffrement, CLI admin) | `app/ingestion/queue.py`, `app/worker.py`, `app/api/jobs.py`, `app/api/ops.py`, `app/admin/**` (nouveau), `app/observability/**`, `app/search/opensearch.py` (client TLS/auth + alias + réplicas), `app/memory/short_term.py` (client Valkey TLS/auth uniquement), `app/storage/**` (S3 + chiffrement enveloppe via `app/crypto.py` nouveau), `app/ingestion/pipeline.py` (refresh/bulk uniquement), `app/models/job.py`, migration `0004`, tests associés |
| **PLATFORM** (déploiement, CI/CD, sauvegardes, supervision, runbooks) | `docker-compose.yml`, `docker-compose.dev.yml` (nouveau), `deploy/**`, `.github/**`, `ops/**`, `backend/Dockerfile`, `backend/docker/**`, `frontend/Dockerfile`, `frontend/next.config.ts` (en-têtes CSP/HSTS), `Makefile`, `.env.example`, `docs/operations/**`, `README.md` (sections déploiement/sécurité/exploitation) |
| **FRONTEND-SEC** | `frontend/src/**` (hors `next.config.ts`) : login SSO/MFA/changement forcé, CSRF dans `client.ts`, pages `/account`, `/admin/users`, `/admin/compliance`, `/admin/ops`, délégations, scopes/expiration des clés, dialogue de déclassification, DLQ/retry, correction contraste RGAA des tokens |

Règles : ne modifier que ses fichiers ; besoin ailleurs ⇒ le signaler dans le rapport final. Dépendances déjà ajoutées
(backend : `cryptography boto3 python-pptx openpyxl pytesseract pypdfium2 segno` ; frontend dev : `vitest @testing-library/* jsdom @playwright/test @axe-core/playwright`).
Ne pas ajouter d'autres dépendances sans nécessité absolue (et alors le signaler).
