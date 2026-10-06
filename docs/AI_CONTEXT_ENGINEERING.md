# ORBIT — Chantiers « état de l'art IA & context engineering » (branche `feature/ai-context-engineering`)

Contrat commun. Complète ARCHITECTURE.md, API.md, FEATURES.md (toujours valables). Règles transverses :
- **LLM optionnel partout** : chaque fonction a un repli déterministe ; garde-fou existant (`app/llm/guardrail.py`) : rien au-dessus de
  `ORBIT_LLM_MAX_CLASSIFICATION` vers un LLM externe, PII masquées. Modèles locaux (fastembed) préférés quand ils existent.
- Même gouvernance que le moteur de contexte (ACL, habilitation, mémoire utilisateur privée, audit, codes de raison).
- Chaque fonction derrière un réglage `ORBIT_…` documenté dans `.env.example` et README (défaut sûr), testée sans appel réseau réel
  (faux serveurs / MockTransport), UI française cohérente avec docs/DESIGN_SYSTEM.md.
- Migrations : une par chantier, chaînées après la tête actuelle (`f004`) : `h001` (A) → `h002` (B) → `h003` (C) → `h004` (D) → `h005` (E) → `h006` (F).

## A — Sécurité IA
1. **Injection de prompt indirecte** : détecteur à l'ingestion (règles multilingues FR/EN : instructions adressées à un modèle, « ignore … »,
   rôles système, balises/encodages suspects, liens d'exfiltration, texte caché/zero-width ; classifieur local optionnel) → score + raisons par chunk ;
   au-dessus du seuil : chunk **mis en quarantaine** (non servi, code de raison `EXCLUDED_QUARANTINE`), visible et libérable par un owner (audit).
2. **Spotlighting** : tout contenu servi aux agents est balisé comme donnée non fiable (délimiteurs + consigne d'en-tête dans le contexte et les
   réponses MCP) ; neutralisation des séquences de délimiteurs dans le contenu.
3. **Confiance par source** (`trust`: high/medium/low, défaut par type ; agents = low) intégrée au classement et à la promotion en mémoire ;
   **alerte d'empoisonnement** : rafale de propositions/faits venant d'une seule source récente ou d'un agent.
4. **Rapport de traçabilité (AI Act)** : export (JSON + PDF/HTML imprimable) « quel contexte, quelles sources, quelle décision, quel modèle »,
   par requête, par période ou par décision ; page Paramètres → Conformité IA.

## B — Recherche
1. **Contextual retrieval** : préambule par chunk (LLM si autorisé, sinon déterministe : titre, section, date, source, entités) indexé avec le chunk ;
   réindexation progressive des projets existants (job).
2. **Reranker cross-encoder multilingue** local (fastembed, licence permissive vérifiée, modèle figé et embarqué dans les images) activable
   (`ORBIT_RERANKER=fastembed`), latence mesurée ; repli heuristique.
3. **Réécriture de requête** : multi-query, décomposition des tâches longues, HyDE (LLM) ; repli : expansion par synonymes/entités du projet.
4. **Recherche itérative** : boucle bornée (≤ 3 tours) qui détecte les sous-sujets non couverts et relance une recherche ciblée ; tours tracés
   dans les timings.
5. **Documents visuels** : description des images/schémas/slides (LLM vision si autorisé ; sinon OCR + texte alternatif) indexée ; images
   extraites des PDF/PPTX.

## C — Assemblage
1. **Cache de prompt** : ordre stable (préfixe : consignes, décisions en vigueur, contraintes, snapshot ; puis éléments variables), empreinte
   du préfixe exposée (`cache_prefix_hash`, `cache_prefix_tokens`) + métriques de réutilisation ; option `cache_hints` (format Anthropic
   `cache_control`) dans l'API/MCP.
2. **Contexte à la demande** : mode `progressive` (résumé + index des sources et décisions avec identifiants) et outils MCP `expand_source`,
   `get_decision`, `get_memory_item`, `search_more` (même gouvernance, audit).
3. **Profils de contexte par type d'agent** (produit, design, engineering, research, custom) : budget, sections, ordre, seuils ; éditables
   dans Paramètres ; ajustement suggéré à partir des retours.
4. **Compression apprise** : élagage au niveau phrase (scoring par embeddings + modèle d'élagage local si disponible), respect des citations.
5. **Suffisance du contexte** : score + verdict `sufficient|partial|insufficient` avec les sous-sujets manquants ; affiché dans l'Explorateur,
   renvoyé aux agents, « Je ne sais pas » assumé par Demander à ORBIT.

## D — Mémoire
1. **Mémoire procédurale / skills** : nouveau type `procedure` (gabarits, définitions de « terminé », conventions, checklists) servi comme
   *skills* (format Agent Skills : SKILL.md + métadonnées) via API/MCP et injecté selon le type de tâche.
2. **Faits temporels et entités** : validité (valid_from/valid_to) exploitée par une requête « tel que connu au <date> » ; résolution d'entités
   (alias, fusion assistée) ; vue graphe enrichie.
3. **Contradictions par modèle** : NLI local ou LLM-juge (si autorisé) en complément des marqueurs lexicaux ; score et explication.
4. **Réflexion périodique** : synthèse mensuelle « ce qui a changé » en mémoire long terme (proposée, validation humaine).

## E — Évaluation & interopérabilité
1. **Banc d'évaluation** : jeux de questions de référence par projet (création dans l'UI, génération assistée depuis les décisions),
   métriques rappel@k, nDCG, suffisance, fidélité des citations ; exécution à la demande et en CI (seuil bloquant configurable) ; historique.
2. **Apprentissage à partir des retours** : 👍/👎, épingles/exclusions manuelles, décisions de tri → ajustement borné des poids du classement
   par projet (journalisé, réversible).
3. **LLM-juge sur échantillon** des contextes servis (si autorisé) → note de suffisance, alertes de dégradation (FORGE).
4. **MCP au-delà des outils** : *resources* (décisions, snapshots, skills), *prompts* (rédiger une spec, préparer une revue…), *elicitation*.
5. **A2A** : Agent Card d'ORBIT + point d'échange de contexte (handoff signé d'un snapshot entre agents).
6. **OpenTelemetry GenAI** : conventions sémantiques `gen_ai.*` sur toutes les traces (retrieval, LLM, MCP).

## F — Sources
1. **Réunions** : import de transcriptions (VTT/SRT/DOCX Teams/Meet, texte), locuteurs, horodatages ; transcription audio optionnelle via
   API compatible Whisper (`ORBIT_TRANSCRIPTION_*`, garde-fou de classification) ; extraction des décisions/actions avec attribution.
2. **Figma** via preset MCP (serveur officiel Figma Dev Mode ou communautaire) : frames, commentaires.
3. **E-mails de projet** : boîte ou dossier dédié (via presets MCP Microsoft 365 / Google) avec fils regroupés.
