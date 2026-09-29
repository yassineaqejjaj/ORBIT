# Spécification fonctionnelle Atlas

**Version :** 1.0 · **Date :** {{date:J-49}} · **Auteur :** Camille Martin (Product Owner)
**Statut :** brouillon soumis à relecture

## 1. Contexte

Nordalis déploie le flex office sur ses sites. Atlas est l'application de réservation d'espaces de travail qui
accompagnera ce changement, avec un pilote sur le site de Lyon. Cette première version de la spécification traduit
les décisions du kick-off : Atlas est une application mobile native iOS et Android, complétée par un back-office web
pour les services généraux.

## 2. Objectifs

- Réserver un poste ou une salle en moins d'une minute depuis son téléphone.
- Donner une vision de l'occupation par étage.
- Outiller les services généraux pour piloter l'occupation et réduire la surface louée.

## 3. Périmètre

Le pilote couvre les 800 postes de travail et les 42 salles de réunion du site de Lyon, répartis sur quatre étages.
Les sites de Lille et de Nantes seront traités dans une phase ultérieure.

### Hors périmètre

- Parking, restauration, casiers.
- Gestion des visiteurs externes.
- Facturation interne des espaces entre directions.

## 4. Utilisateurs et rôles

| Rôle | Description |
|---|---|
| Collaborateur | Réserve des postes et des salles pour lui-même |
| Manager | Consulte la présence de son équipe, réserve pour elle |
| Services généraux | Gèrent l'inventaire, consultent les statistiques |
| Administrateur | Paramètre l'application et les droits |

## 5. Parcours fonctionnels

### 5.1 Connexion

Le collaborateur crée un compte dans l'application native avec son adresse email professionnelle et un mot de
passe. Une vérification par code envoyé par email est demandée à la première connexion.

### 5.2 Réservation d'un poste

1. Le collaborateur choisit une date et une demi-journée ou une journée complète.
2. L'application affiche la liste des postes disponibles, filtrable par étage et par équipement.
3. Le collaborateur sélectionne un poste et confirme ; une notification push confirme la réservation.

### 5.3 Réservation d'une salle

Le collaborateur choisit un créneau, un nombre de participants et des équipements (écran, visioconférence).
L'application propose les salles disponibles et envoie une invitation de réunion.

### 5.4 Annulation

Le collaborateur peut annuler sa réservation jusqu'à l'heure de début. Les réservations non utilisées sont
signalées aux services généraux dans un rapport hebdomadaire.

## 6. Règles de gestion

- RG1 : un collaborateur ne peut réserver qu'un poste par demi-journée.
- RG2 : les réservations sont ouvertes au plus tard quatre semaines à l'avance.
- RG3 : les postes PMR sont signalés par une icône mais restent réservables par tous.
- RG4 : une salle ne peut être réservée plus de quatre heures consécutives.

## 7. Exigences non fonctionnelles

- Disponibilité de 99,5 % pendant les heures ouvrées.
- Temps d'affichage de la liste des postes inférieur à deux secondes.
- Applications iOS et Android publiées sur le store d'entreprise, compatibles avec les deux dernières versions des systèmes.
- Données hébergées dans l'Union européenne.

## 8. Critères d'acceptation (extraits)

- Étant donné un poste disponible, quand je le réserve, alors il n'apparaît plus comme disponible pour les autres collaborateurs.
- Étant donné une réservation, quand je l'annule, alors le poste redevient disponible immédiatement.

## 9. Questions ouvertes

- Faut-il une intégration avec Microsoft Teams dès le pilote ?
- Quelle règle pour les postes adaptés aux personnes à mobilité réduite ?
- Comment confirmer la présence effective sur le poste ?
