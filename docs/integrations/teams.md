# Microsoft Teams — « Demander à ORBIT » dans un canal

ORBIT répond aux mentions dans un canal Teams via un **webhook sortant** (outgoing webhook). Les réponses
suivent exactement la même gouvernance que la page *Demander à ORBIT* : ACL, habilitation, mémoire
utilisateur privée, caviardage PII, garde-fou LLM. Chaque réponse cite ses sources et renvoie vers l'application.

## Prérequis

1. **Clé de chiffrement** côté serveur : le jeton de sécurité Teams est stocké chiffré (Fernet).
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   # puis dans l'environnement du serveur :
   ORBIT_ENCRYPTION_KEY=<clé générée>
   ```
   Sans cette clé, ORBIT refuse la connexion (« Chiffrement non configuré… »).
2. ORBIT doit être joignable en **HTTPS** depuis Internet par Microsoft Teams (URL publique de l'API).
3. Être **propriétaire** du projet ORBIT, et propriétaire de l'équipe Teams (ou avoir le droit d'y créer des applications).

## Étapes

1. Dans ORBIT : projet → **Demander à ORBIT** → bouton **Connecter Microsoft Teams** (visible des propriétaires).
   Copiez l'**URL de rappel** : `https://<votre-orbit>/api/v1/integrations/teams/<slug-du-projet>`.
2. Dans Teams : *équipe* → **Gérer l'équipe** → **Applications** → **Créer un webhook sortant**.
   - Nom : `ORBIT` (c'est le nom à mentionner : `@ORBIT`) ;
   - URL de rappel : celle copiée à l'étape 1 ;
   - Description : « Questions sur la mémoire du projet ».
   Validez : Teams affiche un **jeton de sécurité** (base64) **une seule fois**.
3. Dans ORBIT, collez ce jeton dans **Jeton de sécurité Teams**, vérifiez l'**URL publique d'ORBIT** (liens « Continuer
   dans ORBIT » et liens vers les sources), puis **Enregistrer**.
4. **Reliez les comptes** : pour chaque personne, l'identifiant Teams (`aadObjectId` Entra ID, ou e-mail) → un membre
   du projet ORBIT. À défaut de lien explicite, un message dont l'e-mail correspond au compte d'un membre est accepté.
   Toute autre personne reçoit « Votre compte Teams n'est pas relié à un membre de ce projet ORBIT ».
5. Testez dans le canal : `@ORBIT Pourquoi a-t-on choisi une PWA ?`

## Sécurité

- **Signature** : chaque requête porte `Authorization: HMAC <base64>` = HMAC-SHA256 du corps brut, avec pour clé le
  jeton Teams décodé (base64). Signature absente ou invalide → `401`.
- **Rejeu** : l'identifiant d'activité Teams n'est accepté qu'une fois (`409` ensuite) ; les messages de plus de
  15 minutes sont refusés (`401`).
- **Droits** : la question est posée *au nom du membre relié* ; il ne voit que ce que l'application lui montrerait.
  Les conversations Teams apparaissent dans son historique privé (canal « Teams »).
- **LLM** : si un LLM est configuré, rien au-dessus de `ORBIT_LLM_MAX_CLASSIFICATION` (C1 par défaut) ne lui est
  envoyé ; sinon la réponse est extractive (phrases citées des sources).
- **Audit** : connexion, modification et déconnexion (`integration.*`) ainsi que chaque question (`ask.question`) sont journalisées.
- Pour **renouveler** le jeton : recréez le webhook dans Teams et collez le nouveau jeton (laisser le champ vide conserve
  l'actuel). **Déconnecter** supprime le jeton chiffré ; le webhook répond alors `404`.

## Format de réponse

Réponse JSON au format message Teams : `{"type": "message", "text": "<markdown>"}` — réponse citée `[S1]…`, liste
**Sources** (liens vers la mémoire ou le document dans ORBIT), avertissements éventuels du garde-fou et lien
« Continuer dans ORBIT ». Les webhooks sortants doivent répondre en moins de 5 secondes : sans LLM la réponse est
quasi immédiate ; avec un LLM distant, privilégiez un modèle rapide.

## Dépannage

| Symptôme | Cause probable |
|---|---|
| Teams : « Le webhook n'a pas répondu » | ORBIT injoignable en HTTPS, ou réponse > 5 s (LLM lent) |
| `401 Signature HMAC Teams invalide` | Jeton collé incorrect ou webhook recréé : collez le nouveau jeton |
| `404 Intégration Teams introuvable` | Mauvais slug dans l'URL de rappel, intégration suspendue ou déconnectée |
| « compte non relié » | Ajoutez le lien aadObjectId/e-mail → membre dans ORBIT |
| `409` à l'enregistrement | `ORBIT_ENCRYPTION_KEY` absente ou invalide sur le serveur |
