# Spécification fonctionnelle Atlas

**Version :** 2.0 · **Date :** {{date:J-6}} · **Auteur :** Camille Martin (Product Owner)
**Statut :** validée pour le pilote · **Remplace :** version 1.0

## 1. Contexte

Nordalis déploie le flex office sur ses sites. Atlas est l'application de réservation d'espaces de travail qui
accompagnera ce changement, avec un pilote sur le site de Lyon à partir du 15 novembre. Depuis l'atelier de cadrage,
Atlas est une PWA (application web progressive) utilisable sur téléphone, sur ordinateur et dans un onglet
Microsoft Teams, en remplacement de l'application mobile native prévue initialement.

## 2. Objectifs

- Réserver un poste ou une salle en moins de 30 secondes, depuis Teams ou depuis son téléphone.
- Retrouver son équipe grâce à la réservation « près de mon équipe ».
- Afficher l'occupation des étages en temps réel.
- Outiller les services généraux pour piloter l'occupation et réduire la surface louée.

## 3. Périmètre

Le site de Lyon compte 650 postes de travail après le réaménagement du 2e étage, ainsi que 38 salles de réunion
réparties sur quatre étages. Le pilote ouvre les étages 2 et 3 à environ 180 collaborateurs, puis l'ensemble du site
si les indicateurs sont atteints. Les sites de Lille et de Nantes seront traités dans une phase ultérieure.

### Hors périmètre

- Parking, restauration, casiers.
- Gestion des visiteurs externes.
- Facturation interne des espaces entre directions.
- Application mobile native (abandonnée au profit de la PWA).

## 4. Utilisateurs et rôles

| Rôle | Description | Groupe d'annuaire |
|---|---|---|
| Collaborateur | Réserve des postes et des salles pour lui-même | atlas-users |
| Manager | Consulte la présence de son équipe, organise des journées d'équipe | atlas-managers |
| Services généraux | Gèrent l'inventaire, les QR codes et les statistiques | atlas-facilities |
| Administrateur | Paramètre l'application | atlas-admins |

## 5. Parcours fonctionnels

### 5.1 Connexion

La connexion se fait par SSO OIDC via le Keycloak de Nordalis. Aucun mot de passe spécifique n'est créé ; l'équipe et
le manager sont récupérés depuis l'annuaire à la première connexion.

### 5.2 Réserver près de mon équipe

1. Depuis la page d'accueil, le collaborateur choisit un jour ; Atlas indique qui, dans son équipe, sera présent.
2. Atlas propose le poste libre le plus proche des membres de l'équipe déjà inscrits.
3. Le collaborateur confirme en un geste ; la réservation apparaît dans son agenda.

### 5.3 Carte des étages

La carte affiche les postes libres, réservés et occupés, rafraîchis toutes les 30 secondes. Les noms des salles
reprennent exactement la signalétique physique.

### 5.4 Réservation d'une salle

Le collaborateur choisit un créneau, un nombre de participants et des équipements ; Atlas propose les salles
disponibles et génère l'invitation de réunion.

### 5.5 Check-in par QR code

Chaque poste et chaque salle portent un QR code. Le collaborateur le scanne à son arrivée avec l'appareil photo du
téléphone. Un code court à six caractères est affiché sous le QR code en cas de lecture impossible.

### 5.6 Réservation récurrente

Un collaborateur peut réserver le même poste chaque semaine, sur huit semaines au plus.

## 6. Règles de gestion

- RG1 : un collaborateur ne peut réserver qu'un poste par demi-journée.
- RG2 : les réservations sont ouvertes au plus tard quatre semaines à l'avance.
- RG3 : les postes adaptés PMR sont réservables en priorité par les collaborateurs concernés jusqu'à la veille 18 h.
- RG4 : une réservation non confirmée par check-in 30 minutes après son début est libérée automatiquement.
- RG5 : les managers voient les jours de présence de leur équipe, jamais la localisation en temps réel.

## 7. Exigences non fonctionnelles

- Conformité RGAA niveau AA vérifiée par un audit externe avant le pilote.
- Données personnelles hébergées dans l'Union européenne.
- Temps de réservation médian inférieur à 30 secondes, mesuré pendant le pilote.
- Fonctionnement sur le réseau invité des sites, sans VPN.
- Disponibilité de 99,5 % pendant les heures ouvrées.

## 8. User stories et critères d'acceptation

- En tant que collaborateur, je veux réserver un poste proche de mon équipe afin de travailler avec elle.
  Critère : Atlas propose un poste situé dans la même zone que les membres déjà inscrits, quand il en existe un.
- En tant que collaborateur, je veux confirmer ma présence par QR code afin de conserver ma réservation.
  Critère : le scan valide la réservation en moins de trois secondes, y compris avec le code court.
- En tant que manager, je veux voir les jours de présence de mon équipe pour organiser une journée d'équipe.
  Critère : la vue équipe n'affiche que les jours, pas les positions.

## 9. Indicateurs du pilote

| Indicateur | Cible |
|---|---|
| Taux d'adoption à quatre semaines | 70 % des collaborateurs des étages pilotes |
| Temps médian de réservation | < 30 secondes |
| Réservations libérées faute de check-in | < 15 % |
| Satisfaction (enquête de fin de pilote) | ≥ 4 sur 5 |

## 10. Questions ouvertes

- Faut-il ouvrir la réservation des postes adaptés aux accompagnants ?
- Quelle durée de conservation pour l'historique des réservations ?
