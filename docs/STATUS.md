# État des fonctionnalités : implémenté, testé, `main`, `preprod`, déployé

Mis à jour le 15/10/2026 (audit ORION du 13/10/2026). Cette matrice dit où en est chaque fonctionnalité ; elle ne
remplace ni le [README](../README.md) (présentation) ni [API.md](API.md) (contrat).

Légende des colonnes :

- **Implémenté** : le code existe dans la branche indiquée.
- **Testé** : fichiers de `backend/tests/` (ou vérification décrite) qui l'exercent.
- **`main`** : présent dans `main` (production fournie par la branche, à la date du 13/10 : `10ebc25`).
- **`preprod`** : présent dans `preprod` (branche d'intégration avant la mise en production du vendredi).
- **Déployé** : en production. Le backend ORBIT se déploie à la main (`railway up`), le frontend par Vercel ; l'état réel de
  la production n'est pas lisible depuis le dépôt. « à confirmer » : à renseigner à la mise en production ;
  « non » : volontairement pas avant le vendredi (gel).

## Fonctionnalités antérieures à l'audit

| Fonctionnalité | Implémenté | Testé | `main` | `preprod` | Déployé |
|---|---|---|---|---|---|
| Ingestion multi-sources, versions, PII, classification, détection d'injection | oui | `test_api_documents`, `test_ingestion_units`, `test_ai_security` | oui | oui | à confirmer |
| Connecteurs natifs (SharePoint/OneDrive, Confluence, Jira) et MCP (Confluence & Jira, Microsoft 365, Google Workspace, Slack, GitHub, Linear, Obsidian, Figma, `custom` réservé aux administrateurs) | oui | `test_feature_connectors*`, `test_feature_mcp` (serveurs MCP simulés) | oui | oui | à confirmer |
| Mémoire à cycle de vie, versions, provenance, revue, arbitrage | oui | `test_memory_lifecycle`, `test_api_memory`, `test_feature_inbox`, `test_memory_extraction` | oui | oui | à confirmer |
| Assemblage de contexte gouverné, codes de raison, ACL / classification | oui | `test_api_context`, `test_context_assembler`, `test_governance_policy`, `test_acl` | oui | oui | à confirmer |
| Snapshots versionnés et diff | oui | `test_api_context`, `test_mcp_server` | oui | oui | à confirmer |
| Mémoire « telle que connue au » (`as_of`, `GET /memory/as-of-diff`) | oui | `test_as_of_diff` | oui | oui | à confirmer |
| Graphe de contradictions (`GET /memory/contradictions`) | oui | `test_contradiction_map` | oui | oui | à confirmer |
| Contexte manquant : `POST /context/requests/{id}/complete`, lacunes de connaissance (`knowledge-gaps`) | oui | `test_api_context`, `test_knowledge_gaps` | oui | oui | à confirmer |
| Piste de décision (`GET /memory/{id}/trail`) | oui | `test_decision_trail` | oui | oui | à confirmer |
| Serveur MCP (12 outils, ressources, prompts) | oui | `test_mcp_server`, `test_ai_assembly`, `test_ai_interop` | oui | oui | à confirmer |
| Demander à ORBIT, intégration Teams | oui | `test_feature_ask*`, `test_feature_teams` | oui | oui | à confirmer |
| Fil des changements, abonnements, webhooks signés, flux SSE | oui | `test_feature_feed`, `test_feature_webhooks`, `test_feature_live_events` | oui | oui | à confirmer |
| Garde-fou LLM (plafond de classification, PII masquées) | oui | `test_feature_llm` | oui | oui | à confirmer |
| Évaluation : bancs, juge LLM, apprentissage (`app/evaluation/`) | oui, partiel | `test_ai_eval`, `test_api_learnings`, `test_learning_sharing` | oui | oui | à confirmer |
| Observabilité (métriques, export NDJSON), audit | oui | `test_api_metrics`, `test_audit` | oui | oui | à confirmer |

## Livré par l'audit du 13/10/2026 (dans `preprod`, pas dans `main`)

| Fonctionnalité | Ticket | Implémenté | Testé | `main` | `preprod` | Déployé |
|---|---|---|---|---|---|---|
| `expand_source` sur un identifiant de document ; mypy : 101 → 31 erreurs, baseline versionnée | NOV-88 | oui | `test_ai_assembly`, `test_mypy_baseline` | non | oui | non |
| Police Montserrat embarquée (build sans réseau) | NOV-89 | oui | build Next.js avec Google Fonts bloqué, lint | non | oui | non |
| Stockage objet S3 / compatible derrière `ObjectStore` (défaut : volume local) | NOV-91 | oui | `test_object_store` (local + S3 simulé `moto`, migration) ; pas de MinIO réel | non | oui | non |
| Garde-fou LLM : `classification` obligatoire, embeddings distants | NOV-78 | oui | `test_feature_llm`, `test_embedding_guardrail` | non | oui | non |
| `classification` des items de snapshot, `max_classification`, `access_scope`, `schema_version`, `GET /agents/self` | NOV-73 | oui | `test_context_contract`, `test_api_context`, `test_acl`, `test_agents`, `test_mcp_server` | non | oui | non |
| Événements de révocation (`*.acl_changed`, `document.classification_changed`, `member.removed`, `agent.revoked`) | NOV-80 | oui | `test_feature_feed`, `test_feature_webhooks` | non | oui | non |
| L'oubli réécrit au repos les contextes et snapshots persistés ; `python -m app.admin purge-forgotten` | NOV-97 | oui | `test_forget_purge` | non | oui | non |
| Entité espace : `workspaces`, `workspace_id` (utilisateurs, projets, clés d'agent, webhooks), `orion_project_id`, `ORBIT_WORKSPACE_ENFORCEMENT=off\|shadow\|enforce` (défaut `off`) | NOV-106 | oui | `test_workspace_migration` (base peuplée), `test_workspace_isolation`, `test_workspace_inventory`, `test_contract_fixtures` | non | en cours (PR) | non |
| OIDC relying party (désactivé par défaut) : jetons de l'IdP, Authorization Code + PKCE, liaison confirmée, table `external_identities` | NOV-109 | oui | `test_oidc`, `test_claims_contract`, `test_workspace_migration`, `test_workspace_inventory` | non | en cours (PR) | non |
| Clés d'agent rattachées espace/projet : rôle explicite, expiration facultative, rotation, `python -m app.admin keys list` / `revoke-misplaced` (sans secret) | NOV-112 (ORBIT) | oui | `test_agent_keys`, `test_workspace_migration` | non | en cours (PR) | non |
| Outil de migration des comptes : inventaire en lecture seule, rapprochement dry-run, `--apply` (sauvegarde + approbation signée), drapeaux `password_login_disabled` / `sso_required`, break-glass | NOV-113 (ORBIT) | oui | `test_accounts_migration`, `test_workspace_migration` | non | en cours (PR) | non (exécution = décision séparée) |
| CI GitHub Actions (ruff, mypy baseline, `alembic check`, pytest, web, builds Docker, audits informatifs) | NOV-87 | oui | exécutée sur la PR (voir l'onglet *Checks*) | non | voir la PR | sans objet |

## Pas encore fait

Voir la feuille de route du [README](../README.md#état-et-feuille-de-route) : SSO OIDC et MFA, audit chaîné, durées de
conservation, sauvegardes, chart Helm, déploiement continu, connecteurs CRM, autorisation externalisée (OpenFGA / OPA),
boucle d'évaluation continue, parcours multi-sauts du graphe de connaissances.

## Tenir ce fichier à jour

À chaque mise en production : passer les lignes `preprod` à `main`, renseigner **Déployé** après vérification de la version
servie (`GET /api/v1/meta`, déploiement Railway / Vercel) et ne cocher « testé » que pour des fichiers de test qui existent.
