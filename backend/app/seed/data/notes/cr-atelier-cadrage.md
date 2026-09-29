# Compte rendu — Atelier de cadrage Atlas

**Date :** {{date:J-35}} · **Durée :** une demi-journée
**Rédaction :** Camille Martin
**Participants :** Camille Martin, Inès Moreau, Léo Bernard, Sarah Nguyen, Marc Dubois (architecte SI, DSI Nordalis)

## Ordre du jour

1. Restitution des premiers entretiens utilisateurs.
2. Étude comparative : application native ou application web progressive (PWA).
3. Intégrations avec le système d'information (annuaire, messagerie, Teams).
4. Planning jusqu'au pilote de Lyon.

## 1. Restitution des entretiens

Léo Bernard présente les tendances des huit premiers entretiens (la synthèse complète suivra). Les collaborateurs
veulent réserver depuis leur ordinateur autant que depuis leur téléphone, et beaucoup souhaitent réserver
directement depuis Microsoft Teams. Plusieurs personnes n'installent jamais d'application mobile professionnelle
sur leur téléphone personnel : l'installation depuis un store est perçue comme un frein.

## 2. Étude comparative native / PWA

Inès Moreau présente l'étude demandée lors du kick-off :

| Critère | Application native | PWA |
|---|---|---|
| Bases de code | 2 (iOS, Android) + back-office web | 1 seule, responsive |
| Délai estimé avant pilote | cinq à six mois | trois mois |
| Accès depuis le poste de travail | non (application séparée) | oui, même application |
| Intégration Teams (onglet) | complexe | native (application web) |
| Notifications | complètes | web push (iOS 16.4 et plus) |
| Lecture de QR code | oui | oui via la caméra du navigateur |

Marc Dubois confirme que la DSI préfère limiter le nombre d'applications mobiles à maintenir et que la flotte de
téléphones professionnels est compatible avec les notifications web.

- Décision : l'application Atlas sera une PWA (application web progressive) plutôt qu'une application mobile native iOS et Android.
- Décision : l'application sera intégrée comme onglet Microsoft Teams dès le pilote.

Cette décision remplace celle du kick-off sur l'application native. Camille Martin mettra à jour la spécification
fonctionnelle en conséquence.

## 3. Intégrations

- Annuaire : synchronisation quotidienne des équipes et des managers depuis l'annuaire d'entreprise.
- Messagerie : invitations de réunion générées pour les réservations de salles.
- Contrainte : les données personnelles des collaborateurs doivent rester hébergées dans l'Union européenne.
- Contrainte : l'application doit fonctionner sur le réseau invité des sites, sans VPN.

## 4. Planning

Le pilote est visé pour la mi-novembre sur deux étages du site de Lyon. Une bêta interne sera ouverte à une
vingtaine de collaborateurs environ trois semaines avant le pilote.

- Risque : le calendrier est serré si l'intégration Teams nécessite une validation sécurité longue.
- Point de vigilance : les notifications web push ne fonctionnent sur iPhone qu'après ajout à l'écran d'accueil.

## Actions

| Action | Responsable | Échéance |
|---|---|---|
| Mettre à jour la spécification (PWA) | Camille Martin | trois semaines |
| Maquettes des parcours mobile-first | Léo Bernard | deux semaines |
| Dossier d'architecture et demande de validation sécurité | Inès Moreau | deux semaines |
| Terminer la synthèse des 12 entretiens | Léo Bernard, Sarah Nguyen | une semaine |
