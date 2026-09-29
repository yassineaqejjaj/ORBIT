# Compte rendu — Kick-off du projet Atlas

**Date :** {{date:J-56}} · **Lieu :** siège Nordalis, salle Confluence (Lyon) et visioconférence
**Rédaction :** Camille Martin (Product Owner)
**Participants :** Julien Roux (directeur de la transformation, sponsor), Camille Martin, Léo Bernard (Product Designer),
Inès Moreau (Lead Engineer), Thomas Lefèvre (responsable des services généraux Lyon), Nadia Haddad (DRH),
Sarah Nguyen (analyste, stagiaire)

## Contexte

Nordalis généralise le flex office sur ses sites à partir de 2026. Le site de Lyon sert de pilote : les équipes y
travaillent déjà en partie sans poste attribué, mais la réservation se fait aujourd'hui dans un tableur partagé et par
messagerie. Les collaborateurs se plaignent de ne pas savoir où s'asseoir près de leur équipe et les services généraux
n'ont aucune visibilité sur le taux d'occupation réel. Julien Roux rappelle que l'objectif est double : améliorer
l'expérience des collaborateurs et réduire la surface louée d'environ 15 % d'ici fin 2027.

## Objectifs du projet Atlas

1. Permettre à chaque collaborateur de réserver un poste ou une salle en moins d'une minute.
2. Afficher l'occupation des étages en temps réel pour faciliter le regroupement des équipes.
3. Fournir aux services généraux un tableau de bord d'occupation (taux par étage, par jour, par équipe).
4. Préparer le déploiement sur les autres sites (Lille, Nantes) après le pilote lyonnais.

## Périmètre initial

- Réservation de postes de travail (flex desks) et de salles de réunion du site de Lyon.
- Gestion des équipements (écran double, poste assis-debout, accès PMR).
- Notifications de rappel et libération automatique des réservations non confirmées.
- Hors périmètre à ce stade : parking, restauration, gestion des visiteurs.

## Décisions

- Décision : l'application Atlas sera une application mobile native iOS et Android, publiée sur les stores internes de Nordalis.
- Décision : Camille Martin est Product Owner du projet et arbitre le backlog ; Inès Moreau porte les choix techniques.
- Décision : un comité de pilotage mensuel réunira le sponsor, la DRH et les services généraux.

## Points de discussion

Inès Moreau souligne que le développement natif suppose deux bases de code et des compétences mobiles que l'équipe
n'a qu'en partie ; elle demande qu'une étude comparative soit menée pendant l'atelier de cadrage. Léo Bernard propose
de lancer rapidement des entretiens utilisateurs (une douzaine) pour valider les parcours prioritaires avant toute
maquette détaillée. Thomas Lefèvre fournira l'inventaire à jour des postes et des salles du site de Lyon.

Nadia Haddad indique que la future politique de télétravail imposera un minimum de présence sur site : Atlas devra
aider les managers à organiser des journées d'équipe.

- Risque : dépendance forte à l'inventaire immobilier, qui n'a pas été mis à jour depuis le dernier réaménagement.
- Risque : charge de l'équipe mobile si deux applications natives doivent être maintenues en parallèle.

## Actions

| Action | Responsable | Échéance |
|---|---|---|
| Planifier et mener 12 entretiens utilisateurs | Léo Bernard | trois semaines |
| Transmettre l'inventaire des postes et salles de Lyon | Thomas Lefèvre | une semaine |
| Rédiger la première version de la spécification fonctionnelle | Camille Martin | deux semaines |
| Étude comparative natif / web progressif | Inès Moreau | atelier de cadrage |

Prochain rendez-vous : atelier de cadrage technique et fonctionnel.
