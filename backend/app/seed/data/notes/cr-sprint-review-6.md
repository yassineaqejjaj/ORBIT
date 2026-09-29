# Compte rendu — Sprint review 6 Atlas

**Date :** {{date:J-4}}
**Rédaction :** Camille Martin
**Participants :** équipe Atlas (Camille Martin, Léo Bernard, Inès Moreau, Sarah Nguyen), Thomas Lefèvre,
six collaborateurs de la bêta interne

## Démonstration

L'équipe a présenté les éléments livrés pendant le sprint 6 :

- connexion SSO OIDC via Keycloak, avec récupération automatique de l'équipe et du manager ;
- carte interactive des étages 2 et 3 avec la disponibilité des postes rafraîchie toutes les 30 secondes ;
- réservation d'un poste en trois gestes depuis la page d'accueil (« Réserver près de mon équipe ») ;
- premier prototype de check-in sur place.

Les collaborateurs de la bêta apprécient la réservation près de l'équipe. Deux personnes signalent qu'elles ne
trouvent pas les salles du 3e étage sur la carte (nommage différent de la signalétique).

## Check-in sur le poste

Le check-in évite les réservations fantômes : sans confirmation de présence, le poste est libéré. Deux options ont
été testées : check-in par géolocalisation et check-in par QR code collé sur le poste. La géolocalisation n'est pas
assez précise à l'intérieur du bâtiment.

- Décision : le check-in se fera par QR code apposé sur chaque poste et à l'entrée de chaque salle.
- Décision : une réservation non confirmée 30 minutes après l'heure de début est libérée automatiquement.

Thomas Lefèvre se charge de l'impression et de la pose des étiquettes QR code sur les 650 postes du site.

## Retours de la bêta

- La lecture du QR code est difficile en faible luminosité (fond de salle, fin de journée).
- La réservation récurrente (tous les mardis, par exemple) est très demandée.
- Les managers veulent voir où sont assis les membres de leur équipe pour organiser les journées d'équipe.

- Risque : adoption faible si la réservation prend plus de 30 secondes ; l'objectif de temps de réservation doit être mesuré pendant le pilote.
- Risque : étiquettes QR code arrachées ou illisibles ; prévoir un code court à saisir en secours.

## Indicateurs du sprint

| Indicateur | Valeur |
|---|---|
| Stories livrées | 9 sur 11 |
| Temps médian de réservation (bêta) | 22 secondes |
| Bugs ouverts bloquants | 1 (ATLAS-110) |

## Prochaines étapes

Le sprint 7 portera sur la réservation récurrente, le mode secours du check-in (code court), la correction du
nommage des salles et le tableau de bord des services généraux. Camille Martin mettra à jour la spécification
fonctionnelle avec la section check-in.
