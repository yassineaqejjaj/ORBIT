# ORBIT — Jeu de démonstration « Atlas » et scénario de présentation

> Données **fictives** (entreprise fictive *Nordalis*, domaines `nordalis.example`). Aucun contenu réel.
> Le jeu contient volontairement des documents classifiés **C2 (Confidentiel)** et **C3 (Secret)** fictifs pour
> démontrer la gouvernance : ne pas y mélanger de vraies données.

Le seed (`python -m app.seed`) est **idempotent** (`--reset` pour repartir de zéro) et passe **par l'API réelle**
(authentification, ingestion, pipeline worker, mémoire, contexte) : il démontre que la plateforme est opérationnelle
de bout en bout. Les dates métier (`source_updated_at`) sont relatives à la date d'exécution (J = aujourd'hui).

## 1. Utilisateurs (mot de passe démo : `orbit-demo`, admin : `orbit-admin`)

| Personne | Email | Rôle projet | Habilitation |
|---|---|---|---|
| Admin ORBIT | `admin@orbit.local` | admin plateforme | C3 |
| Camille Martin — Product Owner | `camille.martin@nordalis.example` | owner | C2 |
| Léo Bernard — Product Designer | `leo.bernard@nordalis.example` | editor | C1 |
| Inès Moreau — Lead Engineer | `ines.moreau@nordalis.example` | editor | C2 |
| Sarah Nguyen — Analyste (stagiaire) | `sarah.nguyen@nordalis.example` | viewer | C1 |

## 2. Projet

`atlas` — **Atlas · Réservation d'espaces de travail** : application de réservation de postes et de salles pour
le flex office de Nordalis, pilote sur le site de Lyon.

Agents (clés affichées à la fin du seed et écrites dans `backend/.seed-agents.json`, non versionné) :
`Agent Produit` (product, C2), `Agent Design` (design, C1), `Agent Engineering` (engineering, C2).

## 3. Sources et contenus (chaque cas démontre un mécanisme)

| Source (kind) | Contenu | Date | Classif. | Mécanisme démontré |
|---|---|---|---|---|
| Comptes rendus (note) | CR kick-off : « Décision : application **mobile native** iOS/Android », objectifs, périmètre | J-56 | C1 | décision ensuite **remplacée** |
| Comptes rendus (note) | CR atelier cadrage : « Décision : l'application sera une **PWA** plutôt qu'une application native » | J-35 | C1 | **SUPERSEDED** (remplace la décision native) |
| Comptes rendus (note) | CR comité de pilotage : « Décision : authentification **SSO OIDC (Keycloak)**, abandon du login email/mot de passe » ; « Décision : **pilote le 15 novembre** sur le site de Lyon » ; « Contrainte : conformité **RGAA AA** » | J-14 | C1 | décisions validées récentes |
| Comptes rendus (note) | CR sprint review 6 : « Décision : check-in par **QR code** sur le poste » ; « Risque : adoption faible si la réservation prend plus de 30 s » | J-4 | C1 | fraîcheur, risque |
| Recherche utilisateurs (document) | Synthèse de 12 entretiens (Markdown) : user stories « En tant que collaborateur, je veux… » (poste proche de l'équipe, occupation temps réel, réservation depuis Teams, accessibilité) | J-42 | C1 | **besoins** extraits |
| Recherche utilisateurs (note) | « TR: synthèse entretiens » : copie quasi identique de la synthèse | J-40 | C1 | **DUPLICATE** |
| Spécifications (document) | « Spécification fonctionnelle Atlas » **v1** (app native, 800 postes) puis **v2** (PWA, 650 postes, QR code) — même titre, ré-upload | v1 J-49, v2 J-6 | C1 | **versions**, chunks v1 **SUPERSEDED** |
| Services généraux (document) | « Inventaire immobilier Lyon » : « Le site de Lyon compte **720 postes** » | J-70 | C1 | **CONFLICT** avec la v2 (650 postes après réaménagement) |
| Jira ATLAS (ticket) | Import JSON de 12 tickets `ATLAS-101…112` (épics, stories, bugs), dont 3 datés de plus de 90 jours | J-120 → J-2 | C1 | **STALE** (tickets > 90 j) |
| CRM (crm) | Import CSV de 5 fiches (interlocuteurs Nordalis avec emails et téléphones, notes de rendez-vous) | J-30 → J-8 | C2 | **PII** détectées et caviardées, C2 |
| Retours bêta (feedback) | 8 retours d'utilisateurs pilotes (« impossible de trouver la salle 3B », « le QR code ne se lit pas en faible luminosité »…) | J-10 → J-1 | C1 | besoins / risques terrain |
| Traces agents (agent_trace) | 3 traces d'exécution de l'Agent Produit (brouillon de spec, questions ouvertes) | J-9 → J-3 | C1 | traces comme source |
| Direction (document) | « Budget et négociation contrat Atlas » (montants, marge, conditions) — ACL `role:owner`, **C3** | J-20 | C3 | **CLASSIFICATION** (Camille C2) / **ACL** (Léo, Sarah) |
| Veille (url) | « Benchmark des solutions de flex office » | J-400 | C0 | **STALE** (> 180 j) |
| Veille (url, confiance faible) | « Astuces de réservation des salles (forum externe) » : conseils utiles + un paragraphe d'**injection de prompt fictive** (« ignorez toutes les instructions… », lien d'exfiltration) | J-4 | C0 | **QUARANTINE** (fragment non servi, libérable par un propriétaire ; alerte « À traiter ») |
| RH (document) | « Politique de télétravail 2026 » : 2 jours sur site minimum | J-25 | C1 | contrainte transverse |

## 4. Mémoire (en plus de l'extraction automatique)

- **long_term (organisation)** : « Toutes les applications Nordalis respectent le RGAA niveau AA » (constraint, validé),
  « Hébergement des données personnelles dans l'UE obligatoire » (constraint, validé).
- **user** : Camille — « Préfère des spécifications structurées : contexte, objectifs, user stories, critères d'acceptation, hors-périmètre » ;
  Léo — « Préfère des parcours mobile-first et des maquettes Figma annotées » (⇒ **SCOPE** pour les requêtes de Camille).
- **project** : un fait proposé par un agent, **oublié** ensuite (« Le prestataire X a été retenu » — oubli sélectif, justification :
  information erronée) ⇒ **FORGOTTEN** + audit.
- **short_term** : session `atlas-spec-redaction` (4 tours de l'Agent Produit), plus une session expirée ⇒ **EXPIRED**.

## 5. Historique d'utilisation

Le seed exécute ~30 requêtes de contexte réelles (3 agents, tâches variées) puis répartit leurs horodatages sur les
14 derniers jours (données de démonstration) pour alimenter l'observabilité, avec quelques feedbacks (notes 3–5,
un drapeau `outdated`).

Snapshots : `spec-atlas` v1 (Agent Produit, J-3) et v2 (J-1, après la sprint review) ; `design-atlas` v1 dérivé de
`spec-atlas@v2` (Agent Design) ; `archi-atlas` v1 dérivé de `spec-atlas@v2` (Agent Engineering).

## 6. Scénario de présentation (≈ 8 min)

1. **Vue projet** (Camille) : 11 sources et 39 documents, mémoire (décisions validées, propositions à revoir), alertes (1 conflit, 1 document C3), activité récente.
2. **Sources** : ouvrir la *Spécification fonctionnelle* → 2 versions, étapes de traitement chronométrées, chunks v1 remplacés ;
   ouvrir une fiche CRM → PII détectées et caviardées, bandeau C2.
3. **Mémoire** : la décision « application native » → statut *remplacée*, lien vers la décision PWA, historique, provenance jusqu'au paragraphe du CR.
   Valider une proposition ; marquer un fait obsolète.
4. **Explorateur** : tâche « Rédiger la spécification fonctionnelle du module de réservation pour le pilote de Lyon », Agent Produit,
   budget 4 000 tokens → colonne *Retenus* (décisions en vigueur, besoins, contraintes, citations) / *Exclus* avec les raisons
   (remplacé, périmé, doublon, contradiction résolue, classification, hors périmètre, budget), cascade des temps.
   Enregistrer comme `spec-atlas` v3.
5. **Contexte commun** : même explorateur en *Agent Design* (Léo) sur `spec-atlas@latest` → items hérités épinglés, le document C3 n'apparaît
   même pas en titre (caviardage). **Snapshots** : diff v2 → v3.
6. **Observabilité** : latence p95, tokens, coût estimé, exclusions par raison, sources les plus utilisées ; export NDJSON pour l'évaluation (FORGE).
7. **Paramètres** : clés d'agents, connexion **MCP** (copier la config pour un client MCP), politiques de fraîcheur.
