# Stockage des fichiers originaux

ORBIT garde les fichiers importés derrière l'abstraction `ObjectStore` (`backend/app/storage/object_store.py`).
Deux backends, choisis par `ORBIT_OBJECT_STORE_BACKEND` :

| Backend | Quand | Configuration |
|---|---|---|
| `local` (défaut) | développement, instance unique | `ORBIT_OBJECT_STORE_PATH` (volume `/data/objects`) |
| `s3` | production, API et worker sur des machines séparées | variables `ORBIT_OBJECT_STORE_S3_*` |

Sans variable, le comportement est celui d'avant : volume local. Un volume local ne peut pas être partagé par
l'API et le worker sur Railway ; S3 lève cette contrainte.

## Configuration S3

| Variable | Rôle |
|---|---|
| `ORBIT_OBJECT_STORE_S3_BUCKET` | **Requis** avec `backend=s3` : l'application refuse de démarrer sans |
| `ORBIT_OBJECT_STORE_S3_ENDPOINT` | URL du service compatible (MinIO, Scaleway, R2…) ; vide = AWS S3 |
| `ORBIT_OBJECT_STORE_S3_REGION` | Région |
| `ORBIT_OBJECT_STORE_S3_ACCESS_KEY`, `_SECRET_KEY` | À fournir ensemble ; sans eux, chaîne d'identifiants AWS par défaut (rôle IAM, environnement) |
| `ORBIT_OBJECT_STORE_S3_PREFIX` | Préfixe de toutes les clés (plusieurs environnements dans un même bucket) |
| `ORBIT_OBJECT_STORE_S3_PATH_STYLE` | `true` (défaut) : `endpoint/bucket/clé`, requis par MinIO ; `false` pour l'adressage virtual-host d'AWS |

Les clés d'objet (`<projet>/<document>/v<version>/<fichier>`) sont identiques dans les deux backends. Les
erreurs du backend sont normalisées : `ObjectNotFoundError` pour une clé absente, `ObjectStoreError` pour le
reste (accès refusé, bucket absent, réseau), sans identifiants ni détails d'infrastructure dans le message. Au
démarrage, ORBIT vérifie le bucket (`HeadBucket`) et journalise une erreur s'il est inaccessible.

Droits minimaux de l'identité S3 : `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` sur `bucket/prefix*`, et
`s3:ListBucket`/`s3:GetBucketLocation` sur le bucket (`HeadBucket`, `HeadObject` sur clé absente).

## Migrer du volume local vers S3

1. Créer le bucket et renseigner les variables `ORBIT_OBJECT_STORE_S3_*` dans l'environnement du script
   (le backend de l'application reste `local` pendant la copie).
2. Simuler : `cd backend && uv run python -m scripts.migrate_object_store --dry-run`
   (`--source` pour un autre répertoire que `ORBIT_OBJECT_STORE_PATH`).
3. Copier : `uv run python -m scripts.migrate_object_store`. Le script est **idempotent** (un objet déjà présent avec le
   même SHA-256 est ignoré, un objet modifié depuis est recopié), vérifie chaque copie par relecture et ne
   supprime rien, ni côté source ni côté cible. Code de sortie 1 si une copie a échoué.
4. Arrêter l'écriture (ou relancer une dernière fois le script juste avant la bascule) puis passer
   `ORBIT_OBJECT_STORE_BACKEND=s3` sur l'API **et** le worker, et redémarrer.
5. Conserver le volume local jusqu'à vérification (téléchargement d'un document existant, réindexation d'un
   document) : le retour arrière consiste à repasser `ORBIT_OBJECT_STORE_BACKEND=local`.

## Tests

`backend/tests/test_object_store.py` exécute la même suite de conformité contre le backend local et contre S3
simulé (`moto`), plus la migration. Un test contre MinIO réel reste possible en pointant `S3ObjectStore` sur
son endpoint.
