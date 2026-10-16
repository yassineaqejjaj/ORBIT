# ORBIT — Contrat de contexte versionné (fixtures partagées avec FORGE et NOVA)

ORBIT sert un `ContextPackage` (`POST /api/v1/projects/{slug}/context`) et un `Snapshot`
(`GET /api/v1/projects/{slug}/snapshots/{name}/{version}`) que **FORGE** et **NOVA** lisent. Ce format est un
contrat : ORBIT en publie la **source de vérité testée** dans `contracts/orbit/` ; FORGE et NOVA en gardent des
copies vérifiables. La matrice des versions de protocole (ORBIT, FAP) est dans
`docs/CONTRACTS.md` du dépôt NOVA (qui décrit aussi le job de chaîne optionnel).

## Fichiers

| Fichier | Contenu (données synthétiques) |
|---|---|
| `contracts/orbit/context_package.json` | contexte réel : passages C1, C2 (mémoire) et C3, un élément masqué par ACL |
| `contracts/orbit/context_package_limited_rights.json` | lecteur à droits limités : seul le passage C1 est servi, les autres sont masqués |
| `contracts/orbit/snapshot.json` | snapshot v7 : C1, C2, C3 et un élément **oublié** (`forgotten`, contenu retiré) |
| `contracts/orbit/manifest.json` | `schema_version` et sha256 de chaque fichier |

Les fichiers sont produits par les **vrais** schémas Pydantic (`model_dump(mode="json")`), sans édition manuelle :

```bash
cd backend
uv run python scripts/export_contract_fixtures.py          # réécrit contracts/orbit/
uv run python scripts/export_contract_fixtures.py --check  # code 1 si les fichiers sont périmés
```

## Ce que la CI vérifie (`backend/tests/test_contract_fixtures.py`, sans service externe)

* les fichiers committés sont exactement ce que les schémas actuels produisent (un champ ajouté, retiré ou
  renommé dans `ContextItem`, `ContextPackage`, `Snapshot`… fait échouer le test tant que les fixtures ne sont pas
  régénérées) ;
* l'ensemble des clés de `items[]` (et de `excluded[]`, du paquet, du snapshot et de ses items) est comparé à une
  **liste figée** dans le test ; `schema_version` est figé lui aussi ;
* le manifeste épingle chaque fichier par hash ; les scénarios obligatoires sont présents (C3, droits limités,
  élément oublié, rien ne fuit des éléments masqués).

`tests/test_context_contract.py` (NOV-73) garde en plus la règle « additif uniquement » : les clés historiques ne
sont ni renommées ni supprimées.

## Changer le contrat

1. Modifier le schéma ; si la clé est nouvelle, l'ajouter aux listes `FROZEN_*` du test et, si le sens change,
   incrémenter `CONTEXT_SCHEMA_VERSION` (`app/schemas/common.py`) puis la matrice de NOVA `docs/CONTRACTS.md`.
2. `uv run python scripts/export_contract_fixtures.py`, committer `contracts/orbit/`.
3. Rafraîchir les copies, dans cet ordre (chaque dépôt documente la commande exacte) :
   FORGE `scripts/sync_contract_fixtures.py --orbit …` puis `scripts/generate_fap_fixtures.py` ; NOVA
   `scripts/sync_contract_fixtures.py --orbit … --fap-request …` puis
   `NOVA_REGENERATE_CONTRACTS=1 pytest tests/contract/test_fap_response_fixtures.py` ; enfin FORGE
   `--fap-response …`.

Limite : les copies ne peuvent pas être comparées à la source dans la CI d'un autre dépôt (chaque CI ne voit que son
dépôt). Chaque copie est vérifiée contre son manifeste ; la comparaison avec la source se fait avec `--check` ou avec
`CONTRACT_SOURCE_ORBIT=<chemin>` (procédure de chaîne dans NOVA `docs/CONTRACTS.md`).
