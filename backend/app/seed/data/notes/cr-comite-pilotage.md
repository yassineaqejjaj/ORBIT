# Compte rendu — Comité de pilotage Atlas n° 2

**Date :** {{date:J-14}}
**Rédaction :** Camille Martin
**Participants :** Julien Roux (sponsor), Nadia Haddad (DRH), Thomas Lefèvre (services généraux), Marc Dubois (DSI),
Camille Martin, Inès Moreau

## Avancement

Camille Martin présente l'avancement : la spécification fonctionnelle a été révisée pour la PWA, les maquettes des
parcours de réservation sont validées par un panel de collaborateurs et les sprints 4 et 5 ont livré la réservation
de poste, la carte des étages et la réservation de salle. Le reste à faire pour le pilote porte sur
l'authentification, le check-in sur place et le tableau de bord des services généraux.

## Authentification

Le login par email et mot de passe prévu dans la première spécification pose problème : il crée un nouveau mot de
passe pour chaque collaborateur et ne respecte pas la politique de sécurité de la DSI. Marc Dubois rappelle que
Nordalis dispose d'un fournisseur d'identité Keycloak déjà utilisé par l'intranet.

- Décision : l'authentification d'Atlas se fera par SSO OIDC via le Keycloak de Nordalis ; le login email / mot de passe est abandonné.
- Décision : les droits (collaborateur, manager, services généraux, administrateur) seront portés par les groupes de l'annuaire.

## Date et périmètre du pilote

Julien Roux souhaite un pilote avant la période de fin d'année, pendant laquelle l'occupation des sites baisse.

- Décision : le pilote démarrera le 15 novembre sur le site de Lyon, aux étages 2 et 3, pour environ 180 collaborateurs.
- Décision : la bêta interne restera ouverte jusqu'au pilote pour recueillir les retours terrain.

## Accessibilité et conformité

Nadia Haddad rappelle l'engagement de Nordalis en matière d'accessibilité numérique et la présence de collaborateurs
en situation de handicap sur le site pilote.

- Contrainte : l'application Atlas doit être conforme au RGAA niveau AA avant l'ouverture du pilote.
- Contrainte : les postes équipés pour les personnes à mobilité réduite restent réservables en priorité par les collaborateurs concernés.

Un audit d'accessibilité externe sera réalisé deux semaines avant le pilote.

## Budget

Le budget reste dans l'enveloppe votée. Le détail des négociations avec les prestataires est traité en comité
restreint et n'est pas diffusé dans ce compte rendu.

## Risques

- Risque : la synchronisation des groupes Keycloak peut retarder l'ouverture des droits managers.
- Risque : l'inventaire des postes doit être fiabilisé après le réaménagement du 2e étage, faute de quoi la carte affichera des postes inexistants.

## Actions

| Action | Responsable | Échéance |
|---|---|---|
| Intégration OIDC Keycloak | Inès Moreau | sprint 6 |
| Planifier l'audit RGAA | Léo Bernard | une semaine |
| Inventaire des postes après réaménagement | Thomas Lefèvre | dix jours |
| Plan de communication du pilote | Nadia Haddad, Camille Martin | trois semaines |
