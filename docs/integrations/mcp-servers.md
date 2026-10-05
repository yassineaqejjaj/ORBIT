# Serveurs MCP utilisés par ORBIT (F6)

ORBIT ingère des connaissances via des serveurs **MCP** (Model Context Protocol) éprouvés : un connecteur de type
`mcp` porte un **préréglage** (`config.preset`) qui fixe la commande ou l'URL du serveur, les champs d'identifiants et de
périmètre affichés par l'assistant, les outils requis et le **plan** de lecture (outil de liste → outil de lecture → document
ORBIT). Code : `backend/app/connectors/mcp/` (`presets.py`, `client.py`, `mapper.py`, `connector.py`).

Les noms d'outils et leurs arguments ci-dessous viennent d'une **découverte réelle** (`initialize` + `list_tools` avec le
client SDK MCP 2.2, identifiants factices) sur les versions épinglées, le 6 octobre 2026. Quand un serveur refuse de démarrer
sans identifiants valides, la liste vient de sa documentation et de son code publiés (signalé « doc »).

## Résumé

| Préréglage | Serveur (version épinglée) | Transport | Outils utilisés par ORBIT | Vérifié |
|---|---|---|---|---|
| `atlassian` | [sooperset/mcp-atlassian](https://github.com/sooperset/mcp-atlassian) **0.23.1** (PyPI) | stdio `mcp-atlassian` | `confluence_search`, `confluence_get_page`, `jira_search` (+ `jira_get_issue` requis) | live : 58 outils |
| `ms365` | [Softeria/ms-365-mcp-server](https://github.com/Softeria/ms-365-mcp-server) **0.158.0** (npm) | stdio `ms-365-mcp-server --read-only --org-mode` | `get-drive-delta`, `download-bytes`, `list-mail-messages`, `list-channel-messages` (sonde `get-drive-root-item` / `get-current-user`) | live : 173 outils |
| `google_workspace` | [taylorwilsdon/google_workspace_mcp](https://github.com/taylorwilsdon/google_workspace_mcp) **workspace-mcp 2.0.1** (PyPI) | stdio `workspace-mcp --tools drive docs sheets [gmail] --read-only` | `search_drive_files`, `get_drive_file_content`, `search_gmail_messages`, `get_gmail_message_content` | live : 67 outils |
| `slack` | [korotovsky/slack-mcp-server](https://github.com/korotovsky/slack-mcp-server) **1.3.0** (npm, binaire Go) | stdio `slack-mcp-server --transport stdio` | `conversations_history`, `conversations_replies`, `channels_list` (sonde) | doc : refuse de démarrer sans jeton valide (`invalid_auth`) |
| `github` | [github/github-mcp-server](https://github.com/github/github-mcp-server) **v1.14.0** | HTTP distant `https://api.githubcopilot.com/mcp/` (Bearer) **ou** binaire local `github-mcp-server stdio --read-only --toolsets repos,issues,pull_requests,discussions` | `list_issues`, `issue_read`, `list_pull_requests`, `list_discussions`, `get_discussion`, `get_file_contents`, `search_repositories` (sonde) | live (image Docker, stdio) : 26 outils ; distant : 401 sans jeton |
| `linear` | [Linear MCP](https://linear.app/docs/mcp) (distant, géré par Linear) | HTTP `https://mcp.linear.app/mcp/readonly` (Bearer) | `list_issues`, `list_projects` | doc : 401 sans jeton ; Bearer clé d'API documenté (FAQ Linear) |
| `obsidian` | [MarkusPfundstein/mcp-obsidian](https://github.com/MarkusPfundstein/mcp-obsidian) **0.2.3** (PyPI) + plugin *Local REST API* | stdio `mcp-obsidian` | `obsidian_list_files_in_vault`, `obsidian_list_files_in_dir`, `obsidian_get_file_contents` | live : 15 outils |
| — (convertisseur) | [microsoft/markitdown](https://github.com/microsoft/markitdown) **markitdown-mcp 0.0.1a7** (PyPI) | stdio `markitdown-mcp` | `convert_to_markdown(uri)` | live : conversion d'un fichier `file://` |
| `custom` | serveur arbitraire (admins plateforme, `ORBIT_MCP_ALLOW_CUSTOM=true`) | stdio (commande) ou HTTP | `resources/list` + `resources/read` | tests |

Les images Docker du backend (`backend/Dockerfile`, `backend/Dockerfile.railway`) installent **au build** Node.js 24.21.0
(archive officielle, SHA-256 vérifié), les paquets npm et uv épinglés ci-dessus et le binaire `github-mcp-server` copié depuis
`ghcr.io/github/github-mcp-server:v1.14.0` : aucun code n'est téléchargé à l'exécution. En développement hors Docker, ORBIT
utilise le binaire installé s'il est dans le `PATH`, sinon la version épinglée via `uvx`/`npx` (téléchargement).

## Détail par serveur

### 1. Confluence & Jira — `mcp-atlassian`

- **Variables** (construites par ORBIT) : `CONFLUENCE_URL`, `JIRA_URL`, puis Cloud : `CONFLUENCE_USERNAME`/`JIRA_USERNAME` +
  `CONFLUENCE_API_TOKEN`/`JIRA_API_TOKEN` ; Data Center : `CONFLUENCE_PERSONAL_TOKEN`/`JIRA_PERSONAL_TOKEN`.
  ORBIT force `READ_ONLY_MODE=true` et `ENABLED_TOOLS=confluence_search,confluence_get_page,jira_search,jira_get_issue`.
- **Plan** : par espace, `confluence_search(query=CQL, limit=50)` avec
  `type = page AND space = "X" [AND lastmodified >= "yyyy-MM-dd HH:mm"] ORDER BY lastmodified ASC` (pagination par clé : la
  date de la page la plus récente du lot), puis `confluence_get_page(page_id, convert_to_markdown=true)` → Markdown.
  Jira : `jira_search(jql="(<JQL>) AND updated >= \"yyyy/MM/dd HH:mm\" ORDER BY updated ASC", start_at=…)` → un document
  « ticket » par clé (`external_id = jira:ORB-1`), statut, type, priorité, description et commentaires.
- **Identifiants** : Cloud → *id.atlassian.com → Sécurité → Jetons d'API* (compte de service en lecture seule) ;
  Data Center → jeton d'accès personnel. Les URL saisies passent le contrôle anti-SSRF.

### 2. Microsoft 365 — `ms-365-mcp-server`

- **Variables** : `MS365_MCP_OAUTH_TOKEN` (mode *Bring Your Own Token*). Arguments `--read-only --org-mode`.
- **Plan** : par drive, `get-drive-delta(driveId, driveItemId="root")` (fichiers + suppressions `deleted`), téléchargement
  `download-bytes(target="/drives/{d}/items/{i}/content")` (base64) → pipeline d'ingestion (formats natifs ou MarkItDown) ;
  option e-mails `list-mail-messages(top, filter="receivedDateTime ge …" | search=KQL)` ; canaux Teams `teamId/channelId`
  → `list-channel-messages`, regroupés en un document par canal et par jour.
- **Limite importante** : le serveur ne gère pas le flux *client credentials* ; en mode headless il faut un jeton Graph délégué
  fourni par une application Entra ID (`Files.Read.All`, `Mail.Read`, `ChannelMessage.Read.All`), qui **expire (~1 h)**.
  Pour une synchronisation planifiée durable de SharePoint, préférez le connecteur natif F5 (client credentials).

### 3. Google Workspace — `workspace-mcp`

- **Variables** : `GOOGLE_SERVICE_ACCOUNT_KEY_JSON` (clé JSON d'un compte de service, secret chiffré) et
  `USER_GOOGLE_EMAIL` (utilisateur impersonné). Arguments `--tools drive docs sheets [gmail] --read-only`.
- **Plan** : `search_drive_files(user_google_email, query="trashed = false and '<dossier>' in parents [and modifiedTime > '…']",
  page_size=50, page_token)` — réponse texte (`- Name: "…" (ID: …, Type: …, Modified: …) Link: …`, `nextPageToken: …`) analysée par
  `mapper.drive_lines` — puis `get_drive_file_content(user_google_email, file_id)` (Docs/Sheets exportés en texte/CSV, Office et PDF
  extraits par le serveur). Gmail (option) : `search_gmail_messages(query)` puis `get_gmail_message_content(message_id)`.
- **Identifiants** : console Google Cloud → compte de service + clé JSON ; console d'administration Workspace → délégation au
  niveau du domaine avec les scopes `drive.readonly`, `documents.readonly`, `spreadsheets.readonly` (`gmail.readonly` si Gmail).

### 4. Slack — `slack-mcp-server`

- **Variables** : `SLACK_MCP_XOXP_TOKEN` (jeton utilisateur `xoxp-`) ou `SLACK_MCP_XOXB_TOKEN` (bot `xoxb-`, canaux où il est
  invité, pas de recherche) ; ORBIT fixe `SLACK_MCP_ENABLED_TOOLS=conversations_history,conversations_replies,channels_list`
  (les outils d'écriture restent désactivés).
- **Plan** : par canal, `conversations_history(channel_id, limit="<N>d" | cursor)` — réponse **CSV** (`MsgID, UserName, RealName,
  ThreadTs, Text, Time, Cursor…`) — et `conversations_replies(channel_id, thread_ts)` pour les fils ; un document Markdown par canal
  et par jour (`external_id = slack:<canal>:<AAAA-MM-JJ>`), re-versionné quand la journée évolue. Le test liste les canaux
  (`channels_list`) pour les proposer dans l'assistant.
- **Identifiants** : *api.slack.com/apps → OAuth & Permissions* : `channels:history`, `groups:history`, `channels:read`,
  `users:read`. Le serveur s'arrête au démarrage si le jeton est refusé : le test affiche son journal (caviardé).

### 5. GitHub — serveur MCP officiel

- **Distant (défaut)** : `https://api.githubcopilot.com/mcp/` avec `Authorization: Bearer <PAT>`, `X-MCP-Toolsets:
  repos,issues,pull_requests,discussions`, `X-MCP-Readonly: true`. Les données transitent par l'infrastructure GitHub.
- **Local** : binaire `github-mcp-server stdio --read-only --toolsets …` dans le conteneur ORBIT, variable
  `GITHUB_PERSONAL_ACCESS_TOKEN`.
- **Plan** (par dépôt `owner/nom`) : `list_issues(since, orderBy=UPDATED_AT, direction=ASC, after)` + `issue_read(method=
  get_comments)` ; `list_pull_requests(state=all, sort=updated, direction=desc)` (arrêt au premier élément plus ancien que le
  curseur) ; option discussions `list_discussions` + `get_discussion` ; documentation `get_file_contents(path)` sur
  `README.md` et `docs/` (fichiers `.md/.mdx/.txt/.rst/.adoc`, ressource embarquée), listée intégralement → suppressions détectées.
- **Identifiants** : *Settings → Developer settings → Fine-grained tokens*, accès en lecture seule aux dépôts choisis (Contents,
  Issues, Pull requests, Discussions).

### 6. Linear — serveur MCP distant officiel

- `https://mcp.linear.app/mcp/readonly` (n'expose que des outils de lecture), `Authorization: Bearer <clé d'API>` : la FAQ
  Linear documente le passage d'une clé d'API ou d'un jeton OAuth en Bearer à la place du flux OAuth interactif. Sans jeton, le
  serveur répond `401` (`WWW-Authenticate: Bearer … resource_metadata=…`, OAuth 2.1 + enregistrement dynamique).
- **Plan** : `list_issues(team, project, updatedAt=<curseur ISO>, orderBy=updatedAt, limit=50, cursor)` → tickets ;
  `list_projects` (option). **Non vérifié en direct** (pas de clé) : les noms d'outils viennent de la documentation ; le test de
  l'assistant affiche les outils réellement exposés et signale tout outil requis absent.
- **Identifiants** : *Settings → Security & access → Personal API keys*, clé en lecture seule, idéalement pour un compte de service.

### 7. Obsidian — `mcp-obsidian`

- **Variables** : `OBSIDIAN_API_KEY`, `OBSIDIAN_HOST`, `OBSIDIAN_PORT` (27124). Le serveur appelle l'API du plugin communautaire
  **Local REST API** (HTTPS) : elle doit être joignable depuis le conteneur ORBIT ; l'hôte passe le contrôle anti-SSRF
  (adresses privées refusées hors `ORBIT_ENV=development`).
- **Plan** : parcours récursif `obsidian_list_files_in_vault` / `obsidian_list_files_in_dir(dirpath)` des dossiers choisis, puis
  `obsidian_get_file_contents(filepath)` pour chaque note `.md` ; listing complet à chaque passage (déduplication par empreinte,
  notes supprimées oubliées).

### 8. MarkItDown — convertisseur de documents

- Pas une source : extracteur de **repli** du pipeline d'ingestion (`app/ingestion/extractors/markitdown.py`) pour les formats
  non lus nativement : PowerPoint (`.pptx`, `.ppt`), Excel (`.xlsx`, `.xls`), Outlook (`.msg`, `.eml`), EPUB, OpenDocument
  (`.odt`, `.ods`, `.odp`), RTF, images. Le fichier est copié dans un répertoire temporaire et converti par
  `convert_to_markdown(uri="file://…")` ; l'étape `extract` du job indique « converti via MarkItDown (MCP) · format source … ».
- `ORBIT_MARKITDOWN_MCP=auto` (défaut : utilisé si `markitdown-mcp` est installé) ou `off`. Indisponible ⇒ l'upload de ces formats
  est refusé, et un document déjà en file échoue avec un motif clair en français.

## Sécurité et flux de données

- **Exécution** : les serveurs stdio tournent **dans le conteneur ORBIT** (utilisateur non-root `orbit`), avec les
  identifiants du connecteur. Seules les commandes des préréglages sont lancées (liste blanche) ; arguments et variables sont
  construits côté serveur. L'environnement du processus est minimal : `PATH`, un `HOME`/`TMPDIR` temporaire supprimé à la fin,
  `USER/SHELL/LANG` neutres, plus les seules variables issues des secrets déchiffrés et de la configuration — jamais
  l'environnement de l'API (`ORBIT_*`, clés cloud…).
- **Serveurs distants** (GitHub distant, Linear) : les données transitent par l'éditeur ; le jeton est envoyé en Bearer.
- **Secrets** : chiffrés Fernet (`ORBIT_ENCRYPTION_KEY`) sous forme d'objet JSON des champs secrets, jamais renvoyés (indice
  masqué), caviardés des erreurs, journaux et sorties `stderr` des serveurs (valeurs connues + motifs `Bearer`, `xox*-`, `ghp_`,
  `lin_api_`…).
- **Moindre privilège** : utilisez des comptes de service et des jetons **en lecture seule**, limités aux espaces/dépôts/canaux
  synchronisés ; ORBIT active en plus les modes lecture seule des serveurs (`READ_ONLY_MODE`, `--read-only`, `/readonly`,
  outils d'écriture Slack désactivés).
- **Classification** : chaque connecteur a une classification par défaut (C1 par défaut, à relever en C2/C3 pour des contenus
  confidentiels) et peut restreindre l'accès aux éditeurs (`role:editor`) ; la classification n'est jamais abaissée ensuite.
- **Limites** : `ORBIT_MCP_TIMEOUT_SECONDS` par appel (processus tué au dépassement), `ORBIT_MCP_MAX_ITEMS` éléments par
  synchronisation (la suite au passage suivant), `ORBIT_MCP_MAX_CONTENT_BYTES` par élément, `ORBIT_MCP_SYNC_TIMEOUT_SECONDS` au total.
- **Serveur personnalisé** : uniquement si `ORBIT_MCP_ALLOW_CUSTOM=true` **et** pour un administrateur de la plateforme ; l'URL
  passe le contrôle anti-SSRF (HTTPS hors développement). Ses ressources (`resources/list`) sont lues et ingérées.
