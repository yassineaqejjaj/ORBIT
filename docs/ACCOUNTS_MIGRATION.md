# ORBIT — Migration des comptes vers le SSO (ADR 001 §8, NOV-113)

Outil : `python -m app.admin accounts …` (à lancer sur le serveur, jamais par l'application). **Aucune exécution en production
n'est faite par le ticket NOV-113** : l'exécution est une décision séparée, après la levée du gel et la validation en préproduction.

Toute commande est en **lecture seule** tant qu'elle ne porte pas `--apply`. Aucune adresse n'est affichée en clair (hachée par
défaut, `--emails masked` pour `a***@domaine`), aucun mot de passe ni secret de clé n'est lu.

## Phases

| Phase ADR §8 | Commande | Écrit en base ? |
|---|---|---|
| 0. Inventaire | `accounts inventory [--emails hash\|masked] [--format json\|csv] [--out f]` | non (transaction `READ ONLY`) |
| 2. Rapprochement | `accounts reconcile --idp-export export.json [--allowed-domain d] --out proposition.json` | non |
| 2. Approbation | `accounts approve --proposal proposition.json --accept <proposal_id>… --approver <nom> --out approbation.json` | non (écrit un fichier signé HMAC, `ORBIT_ACCOUNTS_APPROVAL_KEY`) |
| 2. Liaison | `accounts reconcile --idp-export export.json --apply --approval approbation.json --confirm-backup <id> --operator <nom>` | oui : lie **uniquement** les paires approuvées, tout ou rien |
| 3. Mot de passe | `accounts disable-password --user <e-mail> --apply --confirm-backup <id> --operator <nom>` | oui (compte lié au SSO requis) |
| 3. Retour arrière | `accounts enable-password --user <e-mail> --apply --operator <nom>` | oui, sans sauvegarde exigée |
| 3. Break-glass | `accounts break-glass --user <e-mail> [--unset] --apply --operator <nom>` | oui |

Export de l'IdP attendu : `{"issuer": "<iss>", "subjects": [{"sub", "email", "email_verified", "workspace_id"}]}`.

## Ce que le rapprochement signale

`email_absent`, `email_unverified`, `unexpected_domain` (avec `--allowed-domain`), `no_local_account`, `workspace_mismatch`,
`two_accounts_for_subject` (adresses identiques au `+tag` et à la casse près), `two_subjects_for_account`,
`duplicate_subject_in_export`, `subject_linked_to_another_account`, `account_linked_to_another_subject`,
`only_similar_address`. Une proposition en conflit ne peut ni être approuvée ni appliquée.

## Garde-fous de `--apply`

Refusé (code 2, rien d'écrit) sans : `--operator`, `--confirm-backup <id>` désignant un manifeste
`<ORBIT_ACCOUNTS_BACKUP_DIR>/<id>.json` (`{"id", "created_at", "database"}`) **de la base courante** et de moins de
`ORBIT_ACCOUNTS_BACKUP_MAX_AGE_HOURS` (24) heures, fichier d'approbation à la signature valide et du bon émetteur. Les paires sont
re-vérifiées au moment de l'application : une seule devenue conflictuelle annule tout. Chaque liaison / bascule est auditée
(`account.link`, `account.flags`, avec l'opérateur).

## Drapeaux de compte (`users`)

`password_login_disabled` / `sso_required` : la connexion par mot de passe répond 403 (après vérification du mot de passe, rien n'est révélé
à qui ne le détient pas) ; les clés `orb_…` et les sessions déjà ouvertes ne sont pas touchées. Désactiver le mot de passe exige une
identité SSO liée. `is_break_glass` : au plus un compte, administrateur de la plateforme, jamais forcé hors du mot de passe (contrainte en base) ; son mot de
passe fort est défini avec `PATCH /users/{id}` puis gardé hors ligne.

## Procédure de restauration

1. **Avant** toute écriture : sauvegarde complète de la base (`pg_dump`), puis manifeste `<id>.json` dans `ORBIT_ACCOUNTS_BACKUP_DIR`.
2. **Retour arrière ciblé** (un compte) : `accounts enable-password --user … --apply` (le mot de passe refonctionne aussitôt) ;
   une liaison erronée se retire avec `DELETE /auth/oidc/identity` (le compte lui-même) ou par suppression de la ligne
   `external_identities` après sauvegarde.
3. **Retour arrière global** : restaurer la sauvegarde (`pg_restore`), relancer `python -m app.admin purge-forgotten` (cf. docs/FEATURES.md),
   puis `alembic upgrade head`. La migration `h012` est réversible (`alembic downgrade h011` retire les drapeaux : tous les comptes
   retrouvent le mot de passe).
4. Garder le compte break-glass hors SSO jusqu'à la fin de la phase 4.
